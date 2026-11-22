from __future__ import annotations

import json
import time
from pathlib import Path

from one_dragon.base.operation.application import application_const
from one_dragon.base.operation.operation_edge import node_from
from one_dragon.base.operation.operation_node import operation_node
from one_dragon.base.operation.operation_round_result import OperationRoundResult
from one_dragon.utils import os_utils
from one_dragon.utils.log_utils import log
from zzz_od.application.agent_upgrade import agent_upgrade_const
from zzz_od.application.agent_upgrade.agent_upgrade_config import AgentUpgradeConfig
from zzz_od.application.agent_upgrade.agent_upgrade_game import StopRun, UpgradeGame
from zzz_od.application.agent_upgrade.agent_upgrade_runner import (
    Skip,
    Upgrader,
    describe,
    load_plan,
)
from zzz_od.application.zzz_application import ZApplication
from zzz_od.context.zzz_context import ZContext
from zzz_od.operation.back_to_normal_world import BackToNormalWorld


class AgentUpgradeApp(ZApplication):

    """代理人升级:按升级清单 plan.json 在游戏里升级代理人技能。默认只演练,不花材料。"""

    def __init__(self, ctx: ZContext) -> None:
        ZApplication.__init__(
            self,
            ctx=ctx,
            app_id=agent_upgrade_const.APP_ID,
            op_name=agent_upgrade_const.APP_NAME,
        )
        self.config: AgentUpgradeConfig = self.ctx.run_context.get_config(
            app_id=agent_upgrade_const.APP_ID,
            instance_idx=self.ctx.current_instance_idx,
            group_id=application_const.DEFAULT_GROUP_ID,
        )
        self.steps: list[dict] = []
        self.step_idx: int = 0
        self.apply: bool = False
        self.fails: dict[str, int] = {}  # 每个代理人连续失败的次数
        self.result: dict = {}
        self.result_path: Path | None = None
        self.game: UpgradeGame | None = None
        self.upgrader: Upgrader | None = None

    def handle_init(self) -> None:
        self.steps = []
        self.step_idx = 0
        self.apply = False
        self.fails = {}
        self.result = {}
        self.result_path = None
        self.game = None
        self.upgrader = None

    @operation_node(name='读取升级清单', is_start_node=True, screenshot_before_round=False)
    def load(self) -> OperationRoundResult:
        stamp = time.strftime('%Y-%m-%d_%H%M%S')
        log_dir = Path(os_utils.get_path_under_work_dir('.log', 'agent_upgrade'))
        self.result_path = log_dir / f'{stamp}.json'
        self.game = UpgradeGame(self.ctx, log_dir / stamp)

        plan_path = self.config.resolved_plan_path
        try:
            steps, approved = load_plan(plan_path)
            self.game.precheck()
        except StopRun as e:
            return self.round_fail(str(e))

        only = self.config.only_orders.replace('，', ',').strip()
        if only:
            keep = {int(x) for x in only.split(',') if x.strip().isdigit()}
            steps = [s for s in steps if s['order'] in keep]
        self.steps = steps
        self.apply = self.config.apply and approved
        if self.config.apply and not approved:
            log.info('清单里 approved_by_user 不是 true，只演练')
        log.info(f"{'真的升级' if self.apply else '演练'}，清单 {plan_path}，共 {len(steps)} 步")

        self.upgrader = Upgrader(self.game, self.apply)
        self.result = {
            'started_at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'applied': self.apply,
            'plan': str(plan_path), 'steps': [], 'stopped_reason': None,
            'dennies_before': None, 'dennies_after': None,
        }
        return self.round_success(f'共 {len(steps)} 步')

    @node_from(from_name='读取升级清单')
    @operation_node(name='执行清单', screenshot_before_round=False, node_max_retry_times=1)
    def run_steps(self) -> OperationRoundResult:
        """每一轮执行清单里的一步，执行完回到本节点做下一步；用户点停止时在两步之间停下"""
        if self.step_idx >= len(self.steps):
            return self.round_success('清单执行完')

        step = self.steps[self.step_idx]
        self.step_idx += 1
        what = describe(step)
        # 结构化字段给资源调度员 2.0 网页「导入升级结果」用：按成功的步骤更新技能等级和背包
        record: dict = {
            'order': step['order'], 'what': what,
            'agent': step['agent'], 'type': step['what'], 'skill': step.get('skill'),
            'from': step.get('from'), 'to': step.get('to'), 'cost': step.get('cost', {}),
        }
        if self.fails.get(step['agent'], 0) >= 2:
            record.update(status='skipped', reason='该代理人连续失败两次')
            self.result['steps'].append(record)
            return self.round_wait(what)

        try:
            note = self.upgrader.run_step(step)
            record.update(status='ok', note=note)
            self.fails[step['agent']] = 0
            log.info(f'完成 {what}：{note}')
        except Skip as e:
            record.update(status='skipped', reason=str(e))
            log.info(f'跳过 {what}：{e}')
        except StopRun as e:
            record.update(status='failed', reason=str(e))
            self.result['steps'].append(record)
            self.result['stopped_reason'] = str(e)
            log.error(f'停止：{e}')
            self._write_result()
            return self.round_fail(str(e))
        except Exception as e:  # noqa: BLE001 单步意外出错只记失败，继续下一步
            self.fails[step['agent']] = self.fails.get(step['agent'], 0) + 1
            record.update(status='failed', reason=repr(e))
            log.error(f'失败 {what}', exc_info=True)
        self.result['steps'].append(record)
        return self.round_wait(what)

    @node_from(from_name='执行清单')
    @operation_node(name='保存结果', screenshot_before_round=False)
    def save_result(self) -> OperationRoundResult:
        self._write_result()
        return self.round_success(str(self.result_path))

    @node_from(from_name='保存结果')
    @node_from(from_name='执行清单', success=False)
    @operation_node(name='返回大世界')
    def back_to_world(self) -> OperationRoundResult:
        op = BackToNormalWorld(self.ctx)
        return self.round_by_op_result(op.execute())

    def _write_result(self) -> None:
        """结果写到 .log/agent_upgrade/<时间>.json，逐步记录 ok / skipped / failed 和原因"""
        if self.result_path is None or not self.result:
            return
        if self.upgrader is not None:
            self.result['dennies_before'] = self.upgrader.dennies_before
            self.result['dennies_after'] = self.upgrader.dennies_after
        self.result['finished_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        self.result_path.parent.mkdir(parents=True, exist_ok=True)
        self.result_path.write_text(json.dumps(self.result, ensure_ascii=False, indent=2), encoding='utf-8')
        log.info(f'结果写到 {self.result_path}')
