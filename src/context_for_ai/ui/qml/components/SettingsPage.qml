import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Pane {
    id: page
    required property var facade

    Accessible.id: "settingsPage"
    Accessible.role: Accessible.Pane
    Accessible.name: "Settings"
    Accessible.description: ""

    Connections {
        target: page.facade
        function onSettingsAnnouncement(message, revision) {
            settingsStatus.announceRevision(message, revision)
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 22
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            Label {
                Layout.fillWidth: true
                text: "Settings"
                font.pixelSize: 26
                font.weight: Font.DemiBold
                Accessible.ignored: true
            }
            Button {
                objectName: "settingsRefresh"
                text: "Refresh"
                enabled: page.facade.settings_page_state !== "LOADING"
                         && page.facade.settings_page_state !== "SAVING"
                         && page.facade.settings_page_state !== "SHUTDOWN"
                onClicked: page.facade.refresh_settings()
                Accessible.id: "settingsRefresh"
                Accessible.role: Accessible.Button
                Accessible.name: "Refresh settings"
            }
        }

        ManualPageStatus {
            id: settingsStatus
            Layout.fillWidth: true
            accessibleId: "settingsStatus"
            statusText: page.facade.settings_status_text
            announcementRevision: page.facade.settings_announcement_revision
            announcementText: page.facade.settings_announcement_text
        }

        GridLayout {
            Layout.fillWidth: true
            columns: 2
            Label { text: "Theme"; Accessible.ignored: true }
            ComboBox {
                id: theme
                objectName: "settingsTheme"
                Layout.fillWidth: true
                model: ["SYSTEM", "LIGHT", "DARK"]
                currentIndex: page.facade.settings_pending_theme === "LIGHT" ? 1
                              : page.facade.settings_pending_theme === "DARK" ? 2 : 0
                enabled: page.facade.settings_page_state === "READY"
                         || page.facade.settings_page_state === "VALIDATION_ERROR"
                onActivated: page.facade.set_pending_theme(currentText)
                Accessible.id: "settingsTheme"
                Accessible.role: Accessible.ComboBox
                Accessible.name: "Theme"
                Accessible.description: "System, Light, or Dark"
            }
            Item { Layout.fillWidth: true }
            CheckBox {
                objectName: "settingsContextPanelVisible"
                text: "Show context inspection"
                checked: page.facade.settings_pending_context_panel_visible
                enabled: page.facade.settings_page_state === "READY"
                         || page.facade.settings_page_state === "VALIDATION_ERROR"
                onToggled: page.facade.set_pending_context_panel_visible(checked)
                Accessible.id: "settingsContextPanelVisible"
                Accessible.role: Accessible.CheckBox
                Accessible.name: "Show context inspection"
            }
            Item { Layout.fillWidth: true }
            Button {
                objectName: "settingsSave"
                text: "Save settings"
                enabled: page.facade.settings_save_enabled
                onClicked: page.facade.save_settings()
                Accessible.id: "settingsSave"
                Accessible.role: Accessible.Button
                Accessible.name: "Save settings"
            }
        }

        Label {
            objectName: "settingsConfigurationFingerprint"
            Layout.fillWidth: true
            text: "Configuration fingerprint: " + page.facade.settings_configuration_fingerprint
            wrapMode: Text.WrapAnywhere
            Accessible.id: "settingsConfigurationFingerprint"
            Accessible.role: Accessible.StaticText
            Accessible.name: text
            Accessible.description: ""
        }

        ListView {
            id: configuration
            objectName: "settingsConfiguration"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 4
            model: page.facade.settings_configuration
            Accessible.id: "settingsConfiguration"
            Accessible.role: Accessible.List
            Accessible.name: "Configuration"
            Accessible.description: "Safe read-only configuration values"
            delegate: ItemDelegate {
                required property string accessibleId
                required property string accessibleName
                required property string primaryText
                required property string secondaryText
                required property string detailText
                objectName: accessibleId
                width: configuration.width
                text: primaryText + ": " + secondaryText + ". Origin: " + detailText
                Accessible.id: accessibleId
                Accessible.role: Accessible.ListItem
                Accessible.name: accessibleName
                Accessible.description: ""
            }
        }
    }
}
