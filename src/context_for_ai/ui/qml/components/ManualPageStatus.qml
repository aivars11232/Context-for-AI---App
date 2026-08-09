import QtQuick
import QtQuick.Controls

Item {
    id: statusRoot

    required property string accessibleId
    required property string statusText
    required property int announcementRevision
    required property string announcementText
    property int announcedRevision: 0

    objectName: accessibleId
    implicitHeight: statusLabel.implicitHeight
    visible: statusText.length > 0
    Accessible.id: accessibleId
    Accessible.role: Accessible.StaticText
    Accessible.name: statusText
    Accessible.description: ""
    Accessible.ignored: !visible

    function announceRevision(message, revision) {
        if (revision > announcedRevision && message.length > 0) {
            Accessible.announce(message, Accessible.Polite)
            announcedRevision = revision
        }
    }

    Label {
        id: statusLabel
        anchors.left: parent.left
        anchors.right: parent.right
        text: statusRoot.statusText
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: palette.text
        Accessible.ignored: true
    }
}
