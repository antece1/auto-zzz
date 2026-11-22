from one_dragon_qt.services.app_setting.app_setting_provider import (
    AppSettingProvider,
    SettingType,
)
from zzz_od.application.agent_upgrade.agent_upgrade_const import APP_ID


class AgentUpgradeAppSetting(AppSettingProvider):
    app_id = APP_ID
    setting_type = SettingType.FLYOUT

    @staticmethod
    def get_setting_cls() -> type:
        from zzz_od.gui.app_setting.agent_upgrade_setting_flyout import (
            AgentUpgradeSettingFlyout,
        )

        return AgentUpgradeSettingFlyout
