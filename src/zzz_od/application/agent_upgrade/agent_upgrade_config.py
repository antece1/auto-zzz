from pathlib import Path

from one_dragon.base.operation.application.application_config import ApplicationConfig
from one_dragon.utils import os_utils


def default_plan_path() -> str:
    """默认升级清单位置：config/agent_upgrade/plan.json（已 gitignore，不会提交）"""
    return str(Path(os_utils.get_path_under_work_dir('config', 'agent_upgrade')) / 'plan.json')


class AgentUpgradeConfig(ApplicationConfig):

    def __init__(self, instance_idx: int, group_id: str) -> None:
        ApplicationConfig.__init__(
            self,
            app_id='agent_upgrade',
            instance_idx=instance_idx,
            group_id=group_id,
        )

    @property
    def plan_path(self) -> str:
        """升级清单 plan.json 的路径，留空使用默认位置"""
        return self.get('plan_path', '')

    @plan_path.setter
    def plan_path(self, new_value: str) -> None:
        self.update('plan_path', new_value)

    @property
    def apply(self) -> bool:
        """真的升级。关闭时只演练：导航、截图、读数，不点任何会花材料或丁尼的按钮"""
        return self.get('apply', False)

    @apply.setter
    def apply(self, new_value: bool) -> None:
        self.update('apply', new_value)

    @property
    def only_orders(self) -> str:
        """只执行清单里这些 order，逗号分隔，如 1,2,3；留空执行全部"""
        return self.get('only_orders', '')

    @only_orders.setter
    def only_orders(self, new_value: str) -> None:
        self.update('only_orders', new_value)

    @property
    def resolved_plan_path(self) -> Path:
        """实际使用的清单路径"""
        return Path(self.plan_path.strip() or default_plan_path())
