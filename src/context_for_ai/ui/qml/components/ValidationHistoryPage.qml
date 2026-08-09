import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Pane {
    id: page
    required property var facade

    Accessible.id: "validationHistoryPage"
    Accessible.role: Accessible.Pane
    Accessible.name: "Validation history"
    Accessible.description: ""

    Connections {
        target: page.facade
        function onValidationHistoryAnnouncement(message, revision) {
            validationStatus.announceRevision(message, revision)
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
                text: "Validation history"
                font.pixelSize: 26
                font.weight: Font.DemiBold
                Accessible.ignored: true
            }
            Button {
                objectName: "validationHistoryRefresh"
                text: "Refresh"
                enabled: page.facade.validation_history_page_state !== "LOADING"
                         && page.facade.validation_history_page_state !== "SHUTDOWN"
                onClicked: page.facade.refresh_validation_history()
                Accessible.id: "validationHistoryRefresh"
                Accessible.role: Accessible.Button
                Accessible.name: "Refresh validation history"
            }
        }

        ManualPageStatus {
            id: validationStatus
            Layout.fillWidth: true
            accessibleId: "validationHistoryStatus"
            statusText: page.facade.validation_history_status_text
            announcementRevision: page.facade.validation_history_announcement_revision
            announcementText: page.facade.validation_history_announcement_text
        }

        ListView {
            id: summary
            Layout.fillWidth: true
            Layout.preferredHeight: Math.max(70, contentHeight)
            model: page.facade.validation_history_summary
            delegate: Label {
                required property string accessibleName
                required property string primaryText
                required property string secondaryText
                width: summary.width
                text: primaryText + ": " + secondaryText
                wrapMode: Text.Wrap
                Accessible.role: Accessible.StaticText
                Accessible.name: accessibleName
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            ColumnLayout {
                SplitView.fillWidth: true
                Label { text: "Validation attempts"; font.weight: Font.DemiBold; Accessible.ignored: true }
                ListView {
                    id: attempts
                    objectName: "validationHistoryAttempts"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: page.facade.validation_history_attempts
                    Accessible.id: "validationHistoryAttempts"
                    Accessible.role: Accessible.List
                    Accessible.name: "Validation attempts"
                    delegate: ItemDelegate {
                        required property string accessibleId
                        required property string accessibleName
                        required property string primaryText
                        required property string secondaryText
                        required property string detailText
                        objectName: accessibleId
                        width: attempts.width
                        text: primaryText + "\n" + secondaryText + "\n" + detailText
                        Accessible.id: accessibleId
                        Accessible.role: Accessible.ListItem
                        Accessible.name: accessibleName
                        Accessible.description: secondaryText + " " + detailText
                    }
                }
            }
            ColumnLayout {
                SplitView.fillWidth: true
                Label { text: "Corrections"; font.weight: Font.DemiBold; Accessible.ignored: true }
                ListView {
                    id: corrections
                    objectName: "validationHistoryCorrections"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: page.facade.validation_history_corrections
                    Accessible.id: "validationHistoryCorrections"
                    Accessible.role: Accessible.List
                    Accessible.name: "Corrections"
                    delegate: ItemDelegate {
                        required property string accessibleId
                        required property string accessibleName
                        required property string primaryText
                        objectName: accessibleId
                        width: corrections.width
                        text: primaryText
                        Accessible.id: accessibleId
                        Accessible.role: Accessible.ListItem
                        Accessible.name: accessibleName
                    }
                }
            }
        }
    }
}
