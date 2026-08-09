import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Pane {
    id: page
    required property var facade
    property int archiveRow: -1
    property bool archiveEligible: false

    Connections {
        target: page.facade
        function onChanged() {
            if (page.facade.projects_page_state !== "READY"
                    && page.facade.projects_page_state !== "ARCHIVE_CONFIRMATION") {
                page.archiveRow = -1
                page.archiveEligible = false
            }
        }
        function onProjectsAnnouncement(message, revision) {
            projectsStatus.announceRevision(message, revision)
        }
    }

    Accessible.id: "projectsPage"
    Accessible.role: Accessible.Pane
    Accessible.name: "Projects"
    Accessible.description: ""

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 22
        spacing: 12

        RowLayout {
            Layout.fillWidth: true
            Label {
                Layout.fillWidth: true
                text: "Projects"
                font.pixelSize: 26
                font.weight: Font.DemiBold
                Accessible.ignored: true
            }
            Button {
                objectName: "projectsRefresh"
                text: "Refresh"
                enabled: page.facade.projects_page_state !== "LOADING"
                         && page.facade.projects_page_state !== "SAVING"
                         && page.facade.projects_page_state !== "SHUTDOWN"
                onClicked: page.facade.refresh_projects()
                Accessible.id: "projectsRefresh"
                Accessible.role: Accessible.Button
                Accessible.name: "Refresh projects"
            }
        }

        ManualPageStatus {
            id: projectsStatus
            Layout.fillWidth: true
            accessibleId: "projectsStatus"
            statusText: page.facade.projects_status_text
            announcementRevision: page.facade.projects_announcement_revision
            announcementText: page.facade.projects_announcement_text
        }

        RowLayout {
            Button {
                objectName: "projectClearSelection"
                text: "Clear project selection"
                enabled: page.facade.projects_page_state === "READY"
                onClicked: page.facade.clear_project_selection()
                Accessible.id: "projectClearSelection"
                Accessible.role: Accessible.Button
                Accessible.name: "Clear project selection"
            }
            Button {
                objectName: "projectArchive"
                text: "Archive project"
                enabled: page.archiveRow >= 0 && page.archiveEligible
                         && page.facade.projects_page_state === "READY"
                onClicked: page.facade.request_project_archive(page.archiveRow)
                Accessible.id: "projectArchive"
                Accessible.role: Accessible.Button
                Accessible.name: "Archive project"
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true

            ColumnLayout {
                SplitView.fillWidth: true
                Label { text: "Active projects"; font.weight: Font.DemiBold; Accessible.ignored: true }
                ListView {
                    id: activeList
                    objectName: "activeProjectList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: page.facade.active_projects
                    Accessible.id: "activeProjectList"
                    Accessible.role: Accessible.List
                    Accessible.name: "Active projects"
                    delegate: ItemDelegate {
                        required property string accessibleId
                        required property string accessibleName
                        required property string primaryText
                        required property string secondaryText
                        required property string detailText
                        required property bool actionEnabled
                        required property bool current
                        objectName: accessibleId
                        width: activeList.width
                        text: primaryText + "\n" + secondaryText + "\n" + detailText
                        highlighted: current || page.archiveRow === index
                        onClicked: {
                            page.archiveRow = index
                            page.archiveEligible = actionEnabled
                            page.facade.select_active_project(index)
                        }
                        Accessible.id: accessibleId
                        Accessible.role: Accessible.ListItem
                        Accessible.name: accessibleName
                        Accessible.description: secondaryText + " " + detailText
                    }
                }
            }

            ColumnLayout {
                SplitView.fillWidth: true
                Label { text: "Archived projects"; font.weight: Font.DemiBold; Accessible.ignored: true }
                ListView {
                    id: archivedList
                    objectName: "archivedProjectList"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: page.facade.archived_projects
                    Accessible.id: "archivedProjectList"
                    Accessible.role: Accessible.List
                    Accessible.name: "Archived projects"
                    delegate: ItemDelegate {
                        required property string accessibleId
                        required property string accessibleName
                        required property string primaryText
                        required property string secondaryText
                        required property string detailText
                        objectName: accessibleId
                        width: archivedList.width
                        text: primaryText + "\n" + secondaryText + "\n" + detailText
                        Accessible.id: accessibleId
                        Accessible.role: Accessible.ListItem
                        Accessible.name: accessibleName
                        Accessible.description: secondaryText + " " + detailText
                    }
                }
            }
        }
    }

    Dialog {
        id: archiveDialog
        objectName: "projectArchivePopup"
        parent: Overlay.overlay
        anchors.centerIn: parent
        modal: true
        title: "Archive project?"
        visible: page.facade.projects_page_state === "ARCHIVE_CONFIRMATION"
        onOpened: archiveCancel.forceActiveFocus()
        contentItem: ColumnLayout {
            objectName: "projectArchiveDialog"
            Accessible.id: "projectArchiveDialog"
            Accessible.role: Accessible.Dialog
            Accessible.name: "Archive project?"
            Accessible.description: "This hides the project from new selection. Existing conversation associations, messages, memories, and project data are preserved."

            Label {
                Layout.preferredWidth: 480
                text: "This hides the project from new selection. Existing conversation associations, messages, memories, and project data are preserved."
                wrapMode: Text.Wrap
                Accessible.ignored: true
            }
            RowLayout {
                Button {
                    id: archiveCancel
                    objectName: "projectArchiveCancel"
                    text: "Cancel"
                    onClicked: page.facade.cancel_project_archive()
                    Accessible.id: "projectArchiveCancel"
                    Accessible.role: Accessible.Button
                    Accessible.name: "Cancel"
                }
                Button {
                    objectName: "projectArchiveConfirm"
                    text: "Archive"
                    onClicked: page.facade.confirm_project_archive()
                    Accessible.id: "projectArchiveConfirm"
                    Accessible.role: Accessible.Button
                    Accessible.name: "Archive"
                }
            }
        }
    }
}
