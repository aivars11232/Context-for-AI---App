import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: panel

    required property var facade

    function submitCurrentText() {
        if (composer.text.length > 0 && facade.submit_exact(composer.text)) {
            composer.clear()
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: 34
        anchors.rightMargin: 34
        anchors.topMargin: 26
        anchors.bottomMargin: 28
        spacing: 18

        RowLayout {
            Layout.fillWidth: true

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 3

                Label {
                    text: "Chat"
                    color: "#172033"
                    font.pixelSize: 26
                    font.weight: Font.DemiBold
                }

                Label {
                    text: "One focused request at a time"
                    color: "#64748b"
                    font.pixelSize: 13
                }
            }

            Label {
                objectName: "shellStateLabel"
                text: facade.state
                color: "#475569"
                font.pixelSize: 12
                Accessible.name: "Application status"
            }
        }

        Frame {
            Layout.fillWidth: true
            Layout.fillHeight: true
            padding: 20
            background: Rectangle {
                color: "#ffffff"
                radius: 12
                border.color: "#dbe2ea"
                border.width: 1
            }

            ScrollView {
                anchors.fill: parent
                clip: true

                Column {
                    width: parent.width
                    spacing: 14

                    Label {
                        objectName: "assistantOutput"
                        width: parent.width
                        visible: text.length > 0
                        text: facade.assistant_text
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        color: "#172033"
                        font.pixelSize: 15
                        Accessible.name: "Assistant response"
                    }

                    Label {
                        objectName: "clarificationOutput"
                        width: parent.width
                        visible: text.length > 0
                        text: facade.clarification_text
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        color: "#7c3aed"
                        font.pixelSize: 15
                        Accessible.name: "Clarification request"
                    }

                    Label {
                        objectName: "safeStatusMessage"
                        width: parent.width
                        visible: text.length > 0
                        text: facade.status_message
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        color: "#9f1239"
                        font.pixelSize: 14
                        Accessible.name: "Processing message"
                    }

                    Label {
                        width: parent.width
                        visible: assistantOutput.text.length === 0
                                 && clarificationOutput.text.length === 0
                                 && safeStatusMessage.text.length === 0
                                 && !facade.progress_visible
                        text: "Enter a request below to begin."
                        color: "#94a3b8"
                        font.pixelSize: 14
                    }
                }
            }
        }

        RowLayout {
            objectName: "progressRow"
            Layout.fillWidth: true
            visible: facade.progress_visible
            spacing: 10

            BusyIndicator {
                running: parent.visible
                implicitWidth: 24
                implicitHeight: 24
                Accessible.name: "Processing"
            }

            Label {
                objectName: "progressLabel"
                text: facade.progress_label
                color: "#475569"
                font.pixelSize: 13
            }
        }

        Frame {
            Layout.fillWidth: true
            padding: 12
            background: Rectangle {
                color: "#ffffff"
                radius: 10
                border.color: composer.activeFocus ? "#5267df" : "#cbd5e1"
                border.width: composer.activeFocus ? 2 : 1
            }

            ColumnLayout {
                anchors.fill: parent
                spacing: 10

                TextArea {
                    id: composer
                    objectName: "chatComposer"
                    Layout.fillWidth: true
                    Layout.preferredHeight: 104
                    enabled: facade.input_enabled
                    placeholderText: "Type your request exactly as you want it sent…"
                    wrapMode: TextEdit.Wrap
                    selectByMouse: true
                    background: null
                    Accessible.name: "Message"
                }

                RowLayout {
                    Layout.fillWidth: true

                    Label {
                        Layout.fillWidth: true
                        text: composer.text.length === 0
                              ? "Enter at least one character"
                              : "Text is sent exactly as entered"
                        color: "#94a3b8"
                        font.pixelSize: 11
                    }

                    Button {
                        objectName: "cancelButton"
                        text: "Cancel"
                        visible: facade.cancel_enabled
                        enabled: facade.cancel_enabled
                        onClicked: facade.request_cancellation()
                        Accessible.name: "Cancel processing"
                    }

                    Button {
                        objectName: "submitButton"
                        text: "Send"
                        highlighted: true
                        enabled: facade.submit_enabled && composer.text.length > 0
                        onClicked: panel.submitCurrentText()
                        Accessible.name: "Send message"
                    }
                }
            }
        }
    }
}
