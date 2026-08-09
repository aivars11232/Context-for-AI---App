import QtQuick
import QtQuick.Controls

Column {
    id: collectionRoot

    required property string collectionAccessibleId
    required property string collectionAccessibleName
    required property string collectionAvailability
    required property string collectionDisplayText
    required property var itemModel

    objectName: collectionAccessibleId
    width: parent ? parent.width : implicitWidth
    spacing: 8
    Accessible.id: collectionAccessibleId
    Accessible.role: Accessible.List
    Accessible.name: collectionAccessibleName
    Accessible.description: ""

    Label {
        width: collectionRoot.width
        visible: collectionRoot.collectionDisplayText.length > 0
        text: collectionRoot.collectionAccessibleName + ": "
              + collectionRoot.collectionDisplayText
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: "#64748b"
        font.pixelSize: 13
        Accessible.role: Accessible.StaticText
        Accessible.name: text
        Accessible.description: ""
    }

    Repeater {
        model: collectionRoot.itemModel

        delegate: Column {
            id: itemRoot

            required property string accessibleName
            required property var scalars
            required property var collections
            property real itemIndent: 12

            width: collectionRoot.width
            spacing: 6
            Accessible.role: Accessible.ListItem
            Accessible.name: accessibleName
            Accessible.description: ""

            Label {
                x: itemRoot.itemIndent
                width: itemRoot.width - itemRoot.itemIndent
                text: itemRoot.accessibleName
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: "#1e293b"
                font.pixelSize: 13
                font.weight: Font.DemiBold
                Accessible.ignored: true
            }

            InspectionScalarList {
                x: itemRoot.itemIndent
                width: itemRoot.width - itemRoot.itemIndent
                scalarModel: itemRoot.scalars
            }

            Repeater {
                model: itemRoot.collections

                delegate: Column {
                    id: nestedCollection

                    required property string accessibleId
                    required property string accessibleName
                    required property string availability
                    required property string displayText
                    required property var items

                    objectName: accessibleId
                    x: itemRoot.itemIndent
                    width: itemRoot.width - itemRoot.itemIndent
                    spacing: 6
                    Accessible.id: accessibleId
                    Accessible.role: Accessible.List
                    Accessible.name: accessibleName
                    Accessible.description: ""

                    Label {
                        width: nestedCollection.width
                        visible: nestedCollection.displayText.length > 0
                        text: nestedCollection.accessibleName + ": "
                              + nestedCollection.displayText
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        color: "#64748b"
                        font.pixelSize: 13
                        Accessible.role: Accessible.StaticText
                        Accessible.name: text
                        Accessible.description: ""
                    }

                    Repeater {
                        model: nestedCollection.items

                        delegate: Column {
                            id: nestedItem

                            required property string accessibleName
                            required property var scalars
                            property real itemIndent: 12

                            width: nestedCollection.width
                            spacing: 5
                            Accessible.role: Accessible.ListItem
                            Accessible.name: accessibleName
                            Accessible.description: ""

                            Label {
                                x: nestedItem.itemIndent
                                width: nestedItem.width - nestedItem.itemIndent
                                text: nestedItem.accessibleName
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                color: "#334155"
                                font.pixelSize: 13
                                font.weight: Font.DemiBold
                                Accessible.ignored: true
                            }

                            InspectionScalarList {
                                x: nestedItem.itemIndent
                                width: nestedItem.width - nestedItem.itemIndent
                                scalarModel: nestedItem.scalars
                            }
                        }
                    }
                }
            }
        }
    }
}
