from __future__ import annotations

from typing import TYPE_CHECKING

from one_dragon.base.operation.application.application_config import ApplicationConfig
from one_dragon.base.operation.application.application_factory import ApplicationFactory
from one_dragon.base.operation.application_base import Application
from zzz_od.application.agent_upgrade import agent_upgrade_const
from zzz_od.application.agent_upgrade.agent_upgrade_app import AgentUpgradeApp
from zzz_od.application.agent_upgrade.agent_upgrade_config import AgentUpgradeConfig

if TYPE_CHECKING:
    from zzz_od.context.zzz_context import ZContext


class AgentUpgradeAppFactory(ApplicationFactory):

    def __init__(self, ctx: ZContext) -> None:
        ApplicationFactory.__init__(self, agent_upgrade_const)
        self.ctx: ZContext = ctx

    def create_application(self, instance_idx: int, group_id: str) -> Application:
        return AgentUpgradeApp(self.ctx)

    def create_config(self, instance_idx: int, group_id: str) -> ApplicationConfig:
        return AgentUpgradeConfig(instance_idx=instance_idx, group_id=group_id)
