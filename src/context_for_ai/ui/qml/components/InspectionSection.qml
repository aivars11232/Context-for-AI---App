import QtQuick
import QtQuick.Controls

Frame {
    id: sectionRoot

    required property string sectionAccessibleId
    required property string sectionAccessibleName
    required property var scalarModel
    required property var collectionModel

    width: parent ? parent.width : implicitWidth
    padding: 16
    Accessible.id: sectionAccessibleId
    Accessible.role: Accessible.Grouping
    Accessible.name: sectionAccessibleName
    Accessible.description: ""

    background: Rectangle {
        color: sectionRoot.palette.base
        radius: 10
        border.color: sectionRoot.palette.mid
        border.width: 1
    }

    Column {
        width: parent.width
        spacing: 10

        Label {
            width: parent.width
            text: sectionRoot.sectionAccessibleName
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: palette.text
            font.pixelSize: 16
            font.weight: Font.DemiBold
            Accessible.ignored: true
        }

        InspectionScalarList {
            width: parent.width
            scalarModel: sectionRoot.scalarModel
        }

        Repeater {
            model: sectionRoot.collectionModel

            delegate: InspectionCollection {
                required property string accessibleId
                required property string accessibleName
                required property string availability
                required property string displayText
                required property var items

                width: parent ? parent.width : implicitWidth
                collectionAccessibleId: accessibleId
                collectionAccessibleName: accessibleName
                collectionAvailability: availability
                collectionDisplayText: displayText
                itemModel: items
            }
        }
    }
}
