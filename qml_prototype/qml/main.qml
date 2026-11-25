import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window
import QtQuick.Dialogs

ApplicationWindow {
    id: window
    width: 1200
    height: 800
    minimumWidth: 900
    minimumHeight: 600
    visible: true
    title: "Market Scraper"
    color: "#0f172a"
    flags: Qt.FramelessWindowHint | Qt.Window

    property string mode: "keyword"
    property bool forceRefresh: false
    property bool headless: false
    property string exportFormat: "csv"
    property var exportSelection: []

    function openExport(format) {
        window.exportFormat = format
        window.exportSelection = resultTable.shownRows.slice()
        exportFeedback.text = ""
        exportDialog.open()
    }

    FileDialog {
        id: exportDialog
        objectName: "exportDialog"
        title: window.exportFormat === "csv" ? "Simpan hasil CSV" : "Simpan hasil JSON"
        fileMode: FileDialog.SaveFile
        defaultSuffix: window.exportFormat
        nameFilters: window.exportFormat === "csv" ? ["CSV (*.csv)"] : ["JSON (*.json)"]
        onAccepted: {
            exportFeedback.text = backend.exportRows(selectedFile, window.exportFormat, window.exportSelection)
            window.exportSelection = []
        }
        onRejected: window.exportSelection = []
    }

    ScheduleDialog {
        id: scheduleDialog
        parent: Overlay.overlay
        anchors.centerIn: parent
        controller: backend.schedule
        manualSource: backend.manualSource
    }
    // Saran keyword per source (ditaruh di window — properti yang
    // dideklarasikan di dalam ColumnLayout ternyata tidak terbaca
    // oleh anak-anaknya, ReferenceError di Qt 6.12). Google
    // Research: frekuensi kata dari indeks publikasi. Sisanya
    // (kecuali Shopee): riwayat scrape dari keyword_cache.
    // suggestionsVersion dibaca supaya daftar dihitung ulang tiap
    // ada scrape yang selesai (keyword baru langsung muncul).
    property var suggestionData: backend.suggestionsVersion >= 0
        ? backend.suggestionsFor(backend.currentSource)
        : ({ words: [], pairs: [] })
    // Lokasi Google Reviews TIDAK di-hardcode di sini maupun di
    // scraper: pengguna yang mengetiknya (boleh kosong = tanpa
    // filter lokasi). Default-nya dari config (saat ini kosong).

    // ---------- BAR ATAS (custom, karena frameless) ----------
    Rectangle {
        id: topBar
        height: 48
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        color: "#111827"

        MouseArea {
            anchors.fill: parent
            property point clickPos
            onPressed: (mouse) => { clickPos = Qt.point(mouse.x, mouse.y) }
            onPositionChanged: (mouse) => {
                window.x += mouse.x - clickPos.x
                window.y += mouse.y - clickPos.y
            }
        }

        Text {
            anchors.left: parent.left
            anchors.leftMargin: 16
            anchors.verticalCenter: parent.verticalCenter
            text: "◆  MARKET SCRAPER"
            color: "white"
            font.pixelSize: 15
            font.bold: true
        }
        Text {
            anchors.left: parent.left
            anchors.leftMargin: 16
            anchors.top: parent.top
            anchors.topMargin: 28
            text: "Scrape  •  Simpan ke database  •  Cache-first"
            color: "#94a3b8"
            font.pixelSize: 11
        }

        Row {
            anchors.right: parent.right
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8
            Button {
                text: backend.schedule.activeId ? "Jadwal · " + backend.schedule.activeSource :
                      backend.schedule.automaticEnabled ? "Jadwal · Aktif" : "Jadwal · Mati"
                onClicked: scheduleDialog.open()
            }
            Rectangle {
                width: 36; height: 28; radius: 6; color: "#1e293b"
                Text { anchors.centerIn: parent; text: "—"; color: "white"; font.pixelSize: 16 }
                MouseArea { anchors.fill: parent; onClicked: window.showMinimized() }
            }
            Rectangle {
                width: 36; height: 28; radius: 6; color: "#b91c1c"
                Text { anchors.centerIn: parent; text: "✕"; color: "white"; font.pixelSize: 13 }
                MouseArea { anchors.fill: parent; onClicked: window.close() }
            }
        }
    }

    // ---------- BADAN: SIDEBAR + KONTEN ----------
    RowLayout {
        anchors.top: topBar.bottom
        anchors.bottom: parent.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        spacing: 0

        // SIDEBAR
        Rectangle {
            Layout.preferredWidth: 220
            Layout.fillHeight: true
            color: "#111827"

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 6

                Text {
                    text: "SOURCE"
                    color: "#22d3ee"
                    font.pixelSize: 12
                    font.bold: true
                }
                Text {
                    text: "Pilih salah satu, lalu isi\nkeyword di kanan."
                    color: "#94a3b8"
                    font.pixelSize: 11
                    wrapMode: Text.WordWrap
                }

                Repeater {
                    model: backend.sources
                    delegate: Rectangle {
                        Layout.fillWidth: true
                        height: 42
                        radius: 8
                        color: backend.currentSource === modelData ? "#0891b2" : "#1e293b"
                        Text {
                            anchors.left: parent.left
                            anchors.leftMargin: 12
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData
                            color: "white"
                            font.pixelSize: 13
                            font.bold: backend.currentSource === modelData
                        }
                        MouseArea {
                            anchors.fill: parent
                            enabled: !backend.running
                            onClicked: backend.setSource(modelData)
                        }
                    }
                }

                Item { Layout.fillHeight: true }

            }
        }

        // KONTEN UTAMA
        ColumnLayout {
            Layout.fillWidth: true
            Layout.minimumWidth: 0
            Layout.fillHeight: true
            Layout.margins: 16
            spacing: 12

            Text {
                text: "1  Pilih source   →   2  Isi keyword / URL   →   3  Klik Scrape   →   4  Lihat hasil"
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                color: "#22d3ee"
                font.pixelSize: 12
                font.bold: true
            }

            // Bar kontrol: mode, input, limit, scrape
            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                // Toggle mode Keyword / URL
                Row {
                    spacing: 0
                    Repeater {
                        model: ["keyword", "url"]
                        delegate: Rectangle {
                            width: 78; height: 38
                            radius: 0
                            color: window.mode === modelData ? "#0891b2" : "#1e293b"
                            Text {
                                anchors.centerIn: parent
                                text: modelData === "keyword" ? "Keyword" : "URL"
                                color: "white"
                                font.pixelSize: 13
                                font.bold: window.mode === modelData
                            }
                            MouseArea {
                                anchors.fill: parent
                                onClicked: window.mode = modelData
                            }
                        }
                    }
                }

                TextField {
                    id: inputField
                    Layout.fillWidth: true
                    height: 38
                    placeholderText: window.mode === "keyword" ? "Keyword, mis. mouse / Indonesia" : "Tempel URL lengkap di sini"
                    color: "white"
                    placeholderTextColor: "#64748b"
                    font.pixelSize: 13
                    background: Rectangle { radius: 8; color: "#1e293b" }
                }

                Text { text: "Limit:"; color: "#e2e8f0"; font.pixelSize: 13 }
                TextField {
                    id: limitField
                    width: 70; height: 38
                    text: "60"
                    color: "white"
                    placeholderTextColor: "#64748b"
                    font.pixelSize: 13
                    horizontalAlignment: Text.AlignHCenter
                    validator: IntValidator { bottom: 1; top: 500 }
                    background: Rectangle { radius: 8; color: "#1e293b" }
                }

                Rectangle {
                    width: 130; height: 38; radius: 8
                    color: backend.canScrape ? "#06b6d4" : "#334155"
                    Text {
                        anchors.centerIn: parent
                        text: backend.running ? "Scraping…" : (backend.canScrape ? "▶  Scrape" : "Dipakai jadwal")
                        color: "white"
                        font.pixelSize: 14
                        font.bold: true
                    }
                    MouseArea {
                        anchors.fill: parent
                        enabled: backend.canScrape
                        onClicked: backend.scrape(inputField.text, window.mode,
                                                  parseInt(limitField.text) || 60, window.forceRefresh,
                                                  window.headless, locationField.text)
                    }
                }
                Rectangle {
                    width: 100; height: 38; radius: 8
                    color: backend.running ? "#dc2626" : "#334155"
                    Text {
                        anchors.centerIn: parent
                        text: "■  Stop"
                        color: "white"
                        font.pixelSize: 14
                        font.bold: true
                    }
                    MouseArea {
                        anchors.fill: parent
                        enabled: backend.running
                        onClicked: backend.stopScrape()
                    }
                }
            }

            // Saran keyword (mode keyword saja, semua source kecuali
            // Shopee): Google Research memakai frekuensi kata dari
            // indeks publikasi, sisanya memakai riwayat scrape.
            // Klik chip untuk memakai keyword-nya lagi.
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 6
                visible: window.mode === "keyword" && backend.currentSource !== "Shopee" && window.suggestionData.words.length > 0

                Text {
                    Layout.fillWidth: true
                    wrapMode: Text.WordWrap
                    text: backend.currentSource === "Google Research"
                        ? "Saran keyword — klik untuk memakai (angka = perkiraan jumlah hasil):"
                        : "Riwayat keyword — klik untuk memakai lagi (angka = jumlah hasil terakhir):"
                    color: "#94a3b8"; font.pixelSize: 12
                }
                Flow {
                    Layout.fillWidth: true
                    spacing: 6
                    Repeater {
                        model: window.suggestionData.words.concat(window.suggestionData.pairs)
                        delegate: Rectangle {
                            height: 28; radius: 14
                            color: "#1e293b"; border.color: "#0891b2"; border.width: 1
                            width: chipText.implicitWidth + 20
                            Text {
                                id: chipText
                                anchors.centerIn: parent
                                text: modelData.keyword + " • " + modelData.count
                                color: "#e2e8f0"; font.pixelSize: 12
                            }
                            MouseArea {
                                anchors.fill: parent
                                onClicked: {
                                    inputField.text = modelData.keyword
                                    // Chip riwayat Reviews membawa
                                    // lokasinya — isi kolom lokasi juga
                                    // supaya scrape memakai cache yang
                                    // sama dengan yang ditampilkan.
                                    if (modelData.location) locationField.text = modelData.location
                                }
                            }
                        }
                    }
                }
            }

            // Opsi — checkbox custom (kotak + label) supaya warnanya
            // konsisten dengan tema gelap, tanpa bergantung pada style
            // bawaan CheckBox yang beda-beda per platform.
            // Pakai Flow (bukan RowLayout) supaya kalau jendela sempit,
            // opsinya turun ke baris berikut, bukan saling tumpuk.
            // MouseArea jangan jadi anak langsung Row: Row akan ikut
            // menatanya sebagai item, sehingga lebarnya membengkak dan
            // label-labelnya bertumpuk. Klik label ditangani MouseArea
            // di dalam Text-nya sendiri.
            Flow {
                Layout.fillWidth: true
                spacing: 24
                Row {
                    spacing: 8
                    Rectangle {
                        width: 20; height: 20; radius: 4
                        color: window.headless ? "#0891b2" : "#1e293b"
                        border.color: "#334155"; border.width: 1
                        Text { anchors.centerIn: parent; text: window.headless ? "✓" : ""; color: "white"; font.pixelSize: 13 }
                        MouseArea { anchors.fill: parent; onClicked: window.headless = !window.headless }
                    }
                    Text {
                        text: "Headless (tanpa jendela browser)"; color: "#e2e8f0"; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter
                        MouseArea { anchors.fill: parent; onClicked: window.headless = !window.headless }
                    }
                }
                Row {
                    spacing: 8
                    Text { text: "Lokasi (Google Reviews, opsional):"; color: "#e2e8f0"; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                    TextField {
                        id: locationField
                        width: 180; height: 30
                        placeholderText: "Kota, mis. Padang — kosong = tanpa filter"
                        color: "white"
                        placeholderTextColor: "#64748b"
                        font.pixelSize: 12
                        background: Rectangle { radius: 8; color: "#1e293b" }
                    }
                }
                Row {
                    spacing: 8
                    Rectangle {
                        width: 20; height: 20; radius: 4
                        color: window.forceRefresh ? "#0891b2" : "#1e293b"
                        border.color: "#334155"; border.width: 1
                        Text { anchors.centerIn: parent; text: window.forceRefresh ? "✓" : ""; color: "white"; font.pixelSize: 13 }
                        MouseArea { anchors.fill: parent; onClicked: window.forceRefresh = !window.forceRefresh }
                    }
                    Text {
                        text: "Paksa refresh (abaikan cache)"; color: "#e2e8f0"; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter
                        MouseArea { anchors.fill: parent; onClicked: window.forceRefresh = !window.forceRefresh }
                    }
                }
            }

            // Status
            Rectangle {
                Layout.fillWidth: true
                height: 44
                radius: 8
                color: "#162032"
                Row {
                    anchors.left: parent.left
                    anchors.leftMargin: 12
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 8
                    Text {
                        text: backend.running ? "⏳" : "●"
                        color: backend.running ? "#22d3ee" : "#34d399"
                        font.pixelSize: 16
                    }
                    Text {
                        text: backend.statusText
                        color: "#e2e8f0"
                        font.pixelSize: 12
                        wrapMode: Text.WordWrap
                        width: parent.parent.width - 60
                    }
                }
            }

            // Search tabel
            RowLayout {
                Layout.fillWidth: true
                TextField {
                    id: searchField
                    objectName: "resultFilter"
                    onTextChanged: backend.setFilter(text)
                    Connections {
                        target: backend
                        function onSourceChanged() {
                            searchField.clear()
                            exportFeedback.text = ""
                        }
                    }
                    Layout.fillWidth: true
                    height: 36
                    placeholderText: "Cari di hasil yang tampil…"
                    color: "white"
                    placeholderTextColor: "#64748b"
                    font.pixelSize: 12
                    background: Rectangle { radius: 8; color: "#1e293b" }
                }
                Button {
                    objectName: "exportCsv"
                    text: "Ekspor CSV"
                    enabled: resultTable.shownRows.length > 0 && !backend.running
                    onClicked: window.openExport("csv")
                }
                Button {
                    objectName: "exportJson"
                    text: "Ekspor JSON"
                    enabled: resultTable.shownRows.length > 0 && !backend.running
                    onClicked: window.openExport("json")
                }
            }

            Label {
                id: exportFeedback
                Layout.fillWidth: true
                visible: text !== ""
                color: text.startsWith("Gagal") ? "#fca5a5" : "#e2e8f0"
                wrapMode: Text.Wrap
            }

            ResultsTable {
                id: resultTable
                Layout.fillWidth: true
                Layout.fillHeight: true
                controller: backend
            }
        }
    }
}
