import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Pane {
    id: page

    required property var facade
    property int announcedRevision: 0

    Accessible.id: "contextInspectionPage"
    Accessible.role: Accessible.Pane
    Accessible.name: "Context inspection"
    Accessible.description: ""

    function announceCurrentRevision() {
        const revision = facade.inspection_announcement_revision
        if (revision > announcedRevision
                && facade.inspection_announcement_text.length > 0) {
            statusItem.announce(
                facade.inspection_announcement_text,
                Accessible.Polite
            )
            announcedRevision = revision
        }
    }

    Connections {
        target: page.facade

        function onChanged() {
            page.announceCurrentRevision()
        }
    }

    Component.onCompleted: announceCurrentRevision()

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 26
        anchors.rightMargin: 26
        anchors.topMargin: 22
        anchors.bottomMargin: 24
        spacing: 14

        RowLayout {
            Layout.fillWidth: true

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3

                Label {
                    text: "Context inspection"
                    color: "#172033"
                    font.pixelSize: 26
                    font.weight: Font.DemiBold
                    Accessible.ignored: true
                }

                Label {
                    text: "Durable evidence for the latest accepted request"
                    color: "#64748b"
                    font.pixelSize: 13
                    Accessible.ignored: true
                }
            }

            Button {
                id: refreshButton
                objectName: "contextInspectionRefresh"
                text: "Refresh"
                enabled: page.facade.inspection_refresh_enabled
                onClicked: page.facade.refresh_context_inspection()
                Accessible.id: "contextInspectionRefresh"
                Accessible.role: Accessible.Button
                Accessible.name: "Refresh context inspection"
                Accessible.description: ""
            }
        }

        Item {
            id: statusItem
            objectName: "contextInspectionStatus"
            Layout.fillWidth: true
            implicitHeight: statusLabel.implicitHeight
            visible: page.facade.inspection_status_text.length > 0
            Accessible.id: "contextInspectionStatus"
            Accessible.role: Accessible.StaticText
            Accessible.name: page.facade.inspection_status_text
            Accessible.description: ""
            Accessible.ignored: !visible

            function announce(message, politeness) {
                Accessible.announce(message, politeness)
            }

            Label {
                id: statusLabel
                anchors.left: parent.left
                anchors.right: parent.right
                text: page.facade.inspection_status_text
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: page.facade.inspection_page_state === "LOAD_ERROR"
                       || page.facade.inspection_page_state === "CONTROLLED_FAILURE"
                       ? "#9f1239" : "#475569"
                font.pixelSize: 14
                Accessible.ignored: true
            }
        }

        BusyIndicator {
            Layout.alignment: Qt.AlignHCenter
            visible: page.facade.inspection_page_state === "LOADING"
            running: visible
            Accessible.ignored: true
        }

        ScrollView {
            id: inspectionScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: page.facade.inspection_has_view
            clip: true

            Column {
                width: inspectionScroll.availableWidth
                spacing: 12

                Repeater {
                    objectName: "contextInspectionSectionRepeater"
                    model: page.facade.inspection_sections

                    delegate: InspectionSection {
                        required property string accessibleId
                        required property string accessibleName
                        required property var scalars
                        required property var collections

                        objectName: accessibleId
                        width: parent ? parent.width : implicitWidth
                        sectionAccessibleId: accessibleId
                        sectionAccessibleName: accessibleName
                        scalarModel: scalars
                        collectionModel: collections
                    }
                }
            }
        }
    }
}
