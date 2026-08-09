import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Pane {
    id: page

    required property var facade

    Accessible.id: "memoryPage"
    Accessible.role: Accessible.Pane
    Accessible.name: "Memory"
    Accessible.description: ""

    Connections {
        target: page.facade
        function onMemoryAnnouncement(message, revision) {
            memoryStatus.announceRevision(message, revision)
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
                text: "Memory"
                font.pixelSize: 26
                font.weight: Font.DemiBold
                Accessible.ignored: true
            }

            Button {
                id: refreshButton
                objectName: "memoryRefresh"
                text: "Refresh"
                enabled: page.facade.memory_page_state !== "LOADING"
                         && page.facade.memory_page_state !== "SAVING"
                         && page.facade.memory_page_state !== "SHUTDOWN"
                onClicked: page.facade.refresh_memories()
                Accessible.id: "memoryRefresh"
                Accessible.role: Accessible.Button
                Accessible.name: "Refresh memories"
                Accessible.description: ""
            }
        }

        ManualPageStatus {
            id: memoryStatus
            Layout.fillWidth: true
            accessibleId: "memoryStatus"
            statusText: page.facade.memory_status_text
            announcementRevision: page.facade.memory_announcement_revision
            announcementText: page.facade.memory_announcement_text
        }

        RowLayout {
            Layout.fillWidth: true

            ComboBox {
                id: memoryFilter
                objectName: "memoryFilter"
                model: ["ACTIVE", "DELETED"]
                currentIndex: page.facade.memory_filter === "DELETED" ? 1 : 0
                enabled: page.facade.memory_page_state !== "LOADING"
                         && page.facade.memory_page_state !== "SAVING"
                onActivated: page.facade.set_memory_filter(currentText)
                Accessible.id: "memoryFilter"
                Accessible.role: Accessible.ComboBox
                Accessible.name: "Memory filter"
                Accessible.description: "Active or Deleted stored memories"
            }

            Button {
                id: createButton
                objectName: "memoryCreate"
                text: "Create memory"
                enabled: page.facade.memory_page_state === "READY"
                         || page.facade.memory_page_state === "EMPTY"
                         || page.facade.memory_page_state === "MUTATION_ERROR"
                onClicked: page.facade.begin_create_memory()
                Accessible.id: "memoryCreate"
                Accessible.role: Accessible.Button
                Accessible.name: "Create memory"
            }

            Button {
                id: editButton
                objectName: "memoryEdit"
                text: "Edit memory"
                enabled: page.facade.memory_page_state === "READY"
                         && page.facade.selected_memory_index >= 0
                         && page.facade.memory_filter === "ACTIVE"
                onClicked: page.facade.begin_edit_memory()
                Accessible.id: "memoryEdit"
                Accessible.role: Accessible.Button
                Accessible.name: "Edit memory"
            }

            Button {
                id: deleteButton
                objectName: "memorySoftDelete"
                text: "Soft-delete"
                enabled: editButton.enabled
                onClicked: page.facade.request_memory_soft_delete()
                Accessible.id: "memorySoftDelete"
                Accessible.role: Accessible.Button
                Accessible.name: "Soft-delete memory"
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: page.facade.memory_page_state !== "EDITING"

            ListView {
                id: memoryList
                objectName: "memoryList"
                SplitView.preferredWidth: 330
                clip: true
                spacing: 4
                model: page.facade.memory_items
                Accessible.id: "memoryList"
                Accessible.role: Accessible.List
                Accessible.name: "Memories"
                Accessible.description: ""

                delegate: ItemDelegate {
                    required property string accessibleId
                    required property string accessibleName
                    required property string primaryText
                    required property string secondaryText
                    required property string detailText
                    required property bool current

                    objectName: accessibleId
                    width: memoryList.width
                    text: primaryText + "\n" + secondaryText + "\n" + detailText
                    highlighted: current
                    onClicked: page.facade.select_memory(index)
                    Accessible.id: accessibleId
                    Accessible.role: Accessible.ListItem
                    Accessible.name: accessibleName
                    Accessible.description: secondaryText + " " + detailText
                }
            }

            ScrollView {
                SplitView.fillWidth: true
                clip: true

                ColumnLayout {
                    width: parent.width
                    spacing: 10

                    ListView {
                        id: detailList
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.max(120, contentHeight)
                        model: page.facade.memory_details
                        delegate: Label {
                            required property string accessibleName
                            required property string primaryText
                            required property string secondaryText
                            width: detailList.width
                            text: primaryText + ": " + secondaryText
                            wrapMode: Text.Wrap
                            Accessible.role: Accessible.StaticText
                            Accessible.name: accessibleName
                        }
                    }

                    Label {
                        text: "Memory sources"
                        font.weight: Font.DemiBold
                        Accessible.ignored: true
                    }

                    ListView {
                        id: sourceList
                        objectName: "memorySources"
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.max(90, contentHeight)
                        model: page.facade.memory_sources
                        Accessible.id: "memorySources"
                        Accessible.role: Accessible.List
                        Accessible.name: "Memory sources"

                        delegate: ItemDelegate {
                            required property string accessibleId
                            required property string accessibleName
                            required property string primaryText
                            required property string secondaryText
                            required property string detailText
                            objectName: accessibleId
                            width: sourceList.width
                            text: primaryText + " — " + secondaryText + " — " + detailText
                            Accessible.id: accessibleId
                            Accessible.role: Accessible.ListItem
                            Accessible.name: accessibleName
                            Accessible.description: text
                        }
                    }

                    Label {
                        text: "Memory revisions"
                        font.weight: Font.DemiBold
                        Accessible.ignored: true
                    }

                    ListView {
                        id: revisionList
                        objectName: "memoryRevisions"
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.max(90, contentHeight)
                        model: page.facade.memory_revisions
                        Accessible.id: "memoryRevisions"
                        Accessible.role: Accessible.List
                        Accessible.name: "Memory revisions"

                        delegate: ItemDelegate {
                            required property string accessibleId
                            required property string accessibleName
                            required property string primaryText
                            required property string secondaryText
                            required property string detailText
                            objectName: accessibleId
                            width: revisionList.width
                            text: primaryText + " — " + secondaryText + " — " + detailText
                            Accessible.id: accessibleId
                            Accessible.role: Accessible.ListItem
                            Accessible.name: accessibleName
                            Accessible.description: text
                        }
                    }
                }
            }
        }

        Pane {
            id: editor
            objectName: "memoryEditor"
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: page.facade.memory_page_state === "EDITING"
            Accessible.id: "memoryEditor"
            Accessible.role: Accessible.Pane
            Accessible.name: "Memory editor"
            Accessible.description: "Create or edit one memory"

            GridLayout {
                anchors.fill: parent
                columns: 2

                Label { text: "Type" }
                ComboBox {
                    id: typeField
                    Layout.fillWidth: true
                    model: ["PROJECT_FACT", "USER_PREFERENCE", "CORRECTION_RULE", "TECHNICAL_ENVIRONMENT", "ARCHIVED_SUMMARY"]
                    currentIndex: Math.max(0, model.indexOf(page.facade.memory_editor_type))
                    enabled: page.facade.memory_editor_mode === "CREATE"
                    Accessible.name: "Type"
                }
                Label { text: "Scope" }
                ComboBox {
                    id: scopeField
                    Layout.fillWidth: true
                    model: ["CONVERSATION", "PROJECT", "GLOBAL"]
                    currentIndex: Math.max(0, model.indexOf(page.facade.memory_editor_scope))
                    enabled: page.facade.memory_editor_mode === "CREATE"
                    Accessible.name: "Scope"
                }
                Label { text: "Content" }
                TextArea { id: contentField; Layout.fillWidth: true; text: page.facade.memory_editor_content; Accessible.name: "Content" }
                Label { text: "Keywords" }
                TextArea { id: keywordsField; Layout.fillWidth: true; text: page.facade.memory_editor_keywords; Accessible.name: "Keywords" }
                Label { text: "Topic terms" }
                TextArea { id: topicsField; Layout.fillWidth: true; text: page.facade.memory_editor_topics; Accessible.name: "Topic terms" }
                Label { text: "Importance" }
                TextField { id: importanceField; Layout.fillWidth: true; text: page.facade.memory_editor_importance; Accessible.name: "Importance" }
                Label { text: "Confidence" }
                TextField { id: confidenceField; Layout.fillWidth: true; text: page.facade.memory_editor_confidence; Accessible.name: "Confidence" }
                Label { text: "Expiry" }
                TextField { id: expiryField; Layout.fillWidth: true; text: page.facade.memory_editor_expiry; placeholderText: "YYYY-MM-DDTHH:MM:SSZ or empty"; Accessible.name: "Expiry" }
                Label { text: "Source description" }
                TextField { id: sourceField; Layout.fillWidth: true; Accessible.name: "Source description" }
                Item { Layout.fillWidth: true }
                Button {
                    text: page.facade.memory_editor_mode === "CREATE" ? "Create" : "Save"
                    enabled: page.facade.memory_page_state === "EDITING"
                    onClicked: page.facade.submit_memory_editor(
                        typeField.currentText,
                        scopeField.currentText,
                        contentField.text,
                        keywordsField.text,
                        topicsField.text,
                        importanceField.text,
                        confidenceField.text,
                        expiryField.text,
                        sourceField.text
                    )
                    Accessible.name: text + " memory"
                }
                Repeater {
                    model: page.facade.memory_errors
                    delegate: Label {
                        required property string accessibleName
                        required property string secondaryText
                        Layout.columnSpan: 2
                        Layout.fillWidth: true
                        text: secondaryText
                        wrapMode: Text.Wrap
                        Accessible.role: Accessible.StaticText
                        Accessible.name: accessibleName
                    }
                }
            }
        }
    }

    Dialog {
        id: duplicateDialog
        objectName: "memoryDuplicatePopup"
        parent: Overlay.overlay
        anchors.centerIn: parent
        modal: true
        title: "Possible duplicate memories"
        visible: page.facade.memory_page_state === "DUPLICATE_GUIDANCE"
        onOpened: duplicateReturn.forceActiveFocus()

        contentItem: ColumnLayout {
            objectName: "memoryDuplicateDialog"
            Accessible.id: "memoryDuplicateDialog"
            Accessible.role: Accessible.Dialog
            Accessible.name: "Possible duplicate memories"
            Accessible.description: "Review possible duplicates before creating a separate memory."

            ListView {
                Layout.preferredWidth: 520
                Layout.preferredHeight: 180
                model: page.facade.memory_duplicates
                delegate: Label {
                    required property string primaryText
                    required property string secondaryText
                    required property string detailText
                    width: ListView.view.width
                    text: primaryText + " — " + secondaryText + " — " + detailText
                    wrapMode: Text.Wrap
                    Accessible.ignored: true
                }
            }
            RowLayout {
                Button {
                    id: duplicateReturn
                    objectName: "memoryDuplicateReturn"
                    text: "Return to memory editor"
                    onClicked: page.facade.return_from_duplicate_guidance()
                    Accessible.id: "memoryDuplicateReturn"
                    Accessible.role: Accessible.Button
                    Accessible.name: "Return to memory editor"
                }
                Button {
                    objectName: "memoryDuplicateProceed"
                    text: "Create separate memory"
                    onClicked: page.facade.proceed_with_duplicate_create()
                    Accessible.id: "memoryDuplicateProceed"
                    Accessible.role: Accessible.Button
                    Accessible.name: "Create separate memory"
                }
            }
        }
    }

    Dialog {
        id: deleteDialog
        objectName: "memoryDeletePopup"
        parent: Overlay.overlay
        anchors.centerIn: parent
        modal: true
        title: "Soft-delete memory?"
        visible: page.facade.memory_page_state === "DELETE_CONFIRMATION"
        onOpened: deleteCancel.forceActiveFocus()

        contentItem: ColumnLayout {
            objectName: "memoryDeleteDialog"
            Accessible.id: "memoryDeleteDialog"
            Accessible.role: Accessible.Dialog
            Accessible.name: "Soft-delete memory?"
            Accessible.description: "This memory will remain available in Deleted with its provenance and revision history. It cannot be edited, deleted again, or restored."

            Label {
                Layout.preferredWidth: 480
                text: "This memory will remain available in Deleted with its provenance and revision history. It cannot be edited, deleted again, or restored."
                wrapMode: Text.Wrap
                Accessible.ignored: true
            }
            TextField {
                id: deleteSource
                Layout.fillWidth: true
                placeholderText: "Source description"
                Accessible.name: "Source description"
            }
            RowLayout {
                Button {
                    id: deleteCancel
                    objectName: "memoryDeleteCancel"
                    text: "Cancel"
                    onClicked: page.facade.cancel_memory_soft_delete()
                    Accessible.id: "memoryDeleteCancel"
                    Accessible.role: Accessible.Button
                    Accessible.name: "Cancel"
                }
                Button {
                    objectName: "memoryDeleteConfirm"
                    text: "Soft-delete"
                    enabled: deleteSource.text.trim().length > 0
                    onClicked: page.facade.confirm_memory_soft_delete(deleteSource.text)
                    Accessible.id: "memoryDeleteConfirm"
                    Accessible.role: Accessible.Button
                    Accessible.name: "Soft-delete"
                }
            }
        }
    }
}
