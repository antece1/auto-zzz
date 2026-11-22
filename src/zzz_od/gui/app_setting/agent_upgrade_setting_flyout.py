from __future__ import annotations

from PySide6.QtWidgets import QVBoxLayout

from one_dragon_qt.utils.config_utils import get_prop_adapter
from one_dragon_qt.widgets.app_setting.app_setting_flyout import AppSettingFlyout
from one_dragon_qt.widgets.setting_card.switch_setting_card import SwitchSettingCard
from one_dragon_qt.widgets.setting_card.text_setting_card import TextSettingCard
from zzz_od.application.agent_upgrade import agent_upgrade_const
from zzz_od.application.agent_upgrade.agent_upgrade_config import default_plan_path


class AgentUpgradeSettingFlyout(AppSettingFlyout):
    """代理人升级配置弹出框"""

    def _setup_ui(self, layout: QVBoxLayout) -> None:
        self.plan_path_opt = TextSettingCard(
            icon='',
            title='升级清单',
            content='plan.json 的路径，留空使用默认位置',
            input_placeholder=default_plan_path(),
            margins=self.card_margins,
        )
        layout.addWidget(self.plan_path_opt)

        self.only_orders_opt = TextSettingCard(
            icon='',
            title='只执行这些步骤',
            content='填清单里的 order，逗号分隔，如 1,2；留空执行全部',
            input_placeholder='全部',
            margins=self.card_margins,
        )
        layout.addWidget(self.only_orders_opt)

        self.apply_opt = SwitchSettingCard(
            icon='',
            title='真的升级',
            content='关闭时只演练，不花材料；开启后还需要清单里 approved_by_user 为 true',
            margins=self.card_margins,
        )
        layout.addWidget(self.apply_opt)

    def init_config(self) -> None:
        config = self.ctx.run_context.get_config(
            app_id=agent_upgrade_const.APP_ID,
            instance_idx=self.ctx.current_instance_idx,
            group_id=self.group_id,
        )
        self.plan_path_opt.init_with_adapter(get_prop_adapter(config, 'plan_path'))
        self.only_orders_opt.init_with_adapter(get_prop_adapter(config, 'only_orders'))
        self.apply_opt.init_with_adapter(get_prop_adapter(config, 'apply'))
