import QtQuick
import QtQuick.Controls

Column {
    id: scalarList

    required property var scalarModel

    width: parent ? parent.width : implicitWidth
    spacing: 5

    Repeater {
        model: scalarList.scalarModel

        delegate: Label {
            required property string label
            required property string displayText
            required property string accessibleName

            width: scalarList.width
            text: label + ": " + displayText
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: palette.text
            font.pixelSize: 13
            Accessible.role: Accessible.StaticText
            Accessible.name: accessibleName
            Accessible.description: ""
        }
    }
}
