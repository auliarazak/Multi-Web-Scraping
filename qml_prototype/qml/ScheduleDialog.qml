import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Dialog {
    id: dialog
    objectName: "scheduleDialog"
    required property var controller
    required property string manualSource

    title: "Jadwal scraping"
    modal: true
    width: Math.min(880, parent.width - 36)
    height: Math.min(620, parent.height - 36)
    padding: 16
    palette.window: "#111827"
    palette.windowText: "#e2e8f0"
    palette.base: "#1e293b"
    palette.text: "#e2e8f0"
    palette.button: "#1e293b"
    palette.buttonText: "#e2e8f0"
    palette.highlight: "#0e7490"
    palette.highlightedText: "#ffffff"
    background: Rectangle { color: "#111827"; radius: 12; border.color: "#334155" }

    property var jobs: []
    property var runs: []
    property int selectedId: 0
    property var selectedJob: jobs.find(job => job.id === selectedId) || null
    property string notice: ""
    property string feedback: ""
    property bool actionFailed: false
    readonly property bool editingRunning: selectedId !== 0 && selectedId === controller.activeId
    readonly property var units: [1, 60, 1440]

    function reload() {
        const state = controller.snapshot()
        jobs = state.jobs
        runs = state.runs
        notice = state.error
        if (selectedId && !selectedJob)
            loadJob(null)
    }

    function loadJob(job) {
        selectedId = job ? job.id : 0
        sourceField.currentIndex = job ? Math.max(0, controller.sources.indexOf(job.source)) : 0
        modeField.currentIndex = job && job.mode === "url" && sourceField.currentText !== "Google Reviews" ? 1 : 0
        queryField.text = job ? job.keyword : ""
        locationField.text = job ? (job.location || "") : ""
        limitField.value = job ? job.limit_rows : 60
        headlessField.checked = job && job.source === "Tokopedia" ? !!job.headless : false
        const minutes = job ? job.interval_minutes : 60
        unitField.currentIndex = minutes % 1440 === 0 ? 2 : minutes % 60 === 0 ? 1 : 0
        intervalField.value = minutes / units[unitField.currentIndex]
        feedback = ""
    }

    function statusLabel(status) {
        const labels = {done: "Berhasil", empty: "Hasil kosong", partial: "Parsial", failed: "Gagal"}
        return labels[status] || "Belum berjalan"
    }

    function timestamp(value) { return value ? value.replace("T", " ") : "—" }

    function errorSummary(run) {
        const error = run.error || ""
        if (error.includes("ERR_HTTP2_PROTOCOL_ERROR"))
            return "Halaman " + run.source + " gagal dimuat karena koneksi HTTP/2 terputus."
        if (error.includes("Executable doesn't exist"))
            return "Browser Playwright tidak ditemukan saat eksekusi ini."
        return error.split("\n")[0]
    }

    function report(error, success) {
        actionFailed = error !== ""
        feedback = error || success
    }

    onOpened: reload()
    Connections {
        target: dialog.controller
        enabled: dialog.visible
        function onChanged() { dialog.reload() }
        function onJobSaved(jobId) { dialog.loadJob(dialog.jobs.find(job => job.id === jobId)) }
    }

    contentItem: ColumnLayout {
        spacing: 10

        RowLayout {
            Layout.fillWidth: true
            Switch {
                id: automaticSwitch
                objectName: "automaticSwitch"
                text: "Jadwal otomatis"
                checked: dialog.controller.automaticEnabled
                onClicked: {
                    const error = dialog.controller.setAutomatic(checked)
                    if (error) {
                        checked = Qt.binding(() => dialog.controller.automaticEnabled)
                        dialog.report(error, "")
                    } else {
                        dialog.feedback = ""
                    }
                }
            }
            Label {
                Layout.fillWidth: true
                text: dialog.controller.automaticEnabled ? "Aktif · Scrape manual tersedia untuk sumber lain." :
                      dialog.controller.activeId ? "Mati · Tugas " + dialog.controller.activeSource + " sedang diselesaikan." :
                      "Mati · Nyalakan untuk mulai menghitung interval."
                color: "#94a3b8"
                wrapMode: Text.Wrap
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 16

            ColumnLayout {
                Layout.preferredWidth: 280
                Layout.fillHeight: true
                spacing: 6

                RowLayout {
                    Layout.fillWidth: true
                    Label { text: "Daftar jadwal"; font.bold: true; Layout.fillWidth: true }
                    Button { text: "Baru"; onClicked: dialog.loadJob(null) }
                }

                ListView {
                    id: jobList
                    objectName: "scheduledJobs"
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    Layout.minimumHeight: 104
                    clip: true
                    spacing: 3
                    model: dialog.jobs
                    ScrollBar.vertical: ScrollBar {}
                    delegate: ItemDelegate {
                        required property var modelData
                        width: jobList.width
                        highlighted: modelData.id === dialog.selectedId
                        text: modelData.source + " · " + modelData.keyword
                        onClicked: dialog.loadJob(modelData)
                        contentItem: Column {
                            spacing: 3
                            Label {
                                width: parent.width
                                text: parent.parent.text
                                elide: Text.ElideRight
                                font.bold: true
                            }
                            Label {
                                width: parent.width
                                text: modelData.id === dialog.controller.activeId ? "Sedang berjalan…" :
                                    !modelData.active ? "Tugas nonaktif" :
                                    !dialog.controller.automaticEnabled ? "Menunggu jadwal otomatis dinyalakan" :
                                    "Berikutnya " + dialog.timestamp(modelData.next_run_at)
                                color: "#94a3b8"
                                elide: Text.ElideRight
                            }
                        }
                    }
                    Label {
                        anchors.centerIn: parent
                        visible: jobList.count === 0
                        text: "Belum ada jadwal."
                        color: "#94a3b8"
                    }
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 7
                Label { text: dialog.selectedId ? "Ubah jadwal" : "Jadwal baru"; font.bold: true }

                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    rowSpacing: 4
                    columnSpacing: 10
                    enabled: !dialog.editingRunning

                    Label { text: "Sumber" }
                    ComboBox {
                        id: sourceField
                        Layout.fillWidth: true
                        model: dialog.controller.sources
                        onActivated: if (currentText === "Google Reviews") modeField.currentIndex = 0
                    }

                    Label { text: "Mode" }
                    ComboBox {
                        id: modeField
                        Layout.fillWidth: true
                        model: ["Keyword", "URL"]
                        enabled: sourceField.currentText !== "Google Reviews"
                    }

                    Label { text: modeField.currentIndex === 1 ? "URL" : "Keyword" }
                    TextField {
                        id: queryField
                        objectName: "scheduleQuery"
                        Layout.fillWidth: true
                        placeholderText: modeField.currentIndex === 1 ? "https://…" : "Masukkan keyword"
                    }

                    Label { text: "Lokasi"; visible: locationField.visible }
                    TextField {
                        id: locationField
                        Layout.fillWidth: true
                        visible: sourceField.currentText === "Google Reviews"
                        placeholderText: "Kota (opsional)"
                    }

                    Label { text: "Limit" }
                    RowLayout {
                        SpinBox { id: limitField; from: 1; to: 500; value: 60; editable: true }
                        CheckBox {
                            id: headlessField
                            objectName: "scheduleHeadless"
                            visible: sourceField.currentText === "Tokopedia"
                            text: "Tanpa jendela (headless)"
                        }
                    }

                    Label { text: "Ulangi setiap" }
                    RowLayout {
                        SpinBox {
                            id: intervalField
                            from: 1
                            to: 525600 / dialog.units[unitField.currentIndex]
                            value: 1
                            editable: true
                        }
                        ComboBox { id: unitField; model: ["Menit", "Jam", "Hari"]; currentIndex: 1 }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Button {
                        objectName: "saveSchedule"
                        text: "Simpan"
                        enabled: !dialog.editingRunning
                        onClicked: dialog.report(dialog.controller.saveJob(
                            dialog.selectedId, sourceField.currentText,
                            modeField.currentIndex === 1 ? "url" : "keyword",
                            queryField.text, limitField.value,
                            intervalField.value * dialog.units[unitField.currentIndex],
                            locationField.text, sourceField.currentText === "Tokopedia" ? headlessField.checked : true),
                            "Jadwal tersimpan.")
                    }
                    Button {
                        objectName: "runScheduleNow"
                        text: "Jalankan sekarang"
                        enabled: !!dialog.selectedJob && dialog.controller.automaticEnabled &&
                                 dialog.controller.activeId === 0 && dialog.selectedJob.source !== dialog.manualSource
                        onClicked: dialog.report(dialog.controller.runNow(dialog.selectedId), "")
                    }
                    Button {
                        text: dialog.selectedJob && dialog.selectedJob.active ? "Nonaktifkan" : "Aktifkan"
                        enabled: dialog.selectedId > 0 && !dialog.editingRunning
                        onClicked: dialog.report(dialog.controller.setJobActive(
                            dialog.selectedId, !dialog.selectedJob.active), "Status jadwal diperbarui.")
                    }
                    Button {
                        text: "Hapus"
                        enabled: dialog.selectedId > 0 && !dialog.editingRunning
                        onClicked: deletePrompt.open()
                    }
                }

                Label {
                    Layout.fillWidth: true
                    visible: dialog.selectedJob !== null
                    text: dialog.editingRunning ? "Scrape terjadwal sedang berjalan…" :
                        dialog.selectedJob ? "Terakhir " + dialog.timestamp(dialog.selectedJob.last_run_at) + " · " +
                        dialog.statusLabel(dialog.selectedJob.last_status) +
                        (dialog.selectedJob.last_run_at ? " · " + dialog.selectedJob.last_rows + " baris" : "") : ""
                    color: "#94a3b8"
                    wrapMode: Text.Wrap
                }
            }
        }

        Label {
            Layout.fillWidth: true
            visible: text !== ""
            text: dialog.notice || dialog.feedback
            color: dialog.notice || dialog.actionFailed ? "#fca5a5" : "#86efac"
            elide: Text.ElideRight
        }

        Label { text: "Riwayat eksekusi"; font.bold: true }
        ListView {
            id: historyList
            objectName: "scheduleHistory"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 60
            clip: true
            spacing: 4
            model: dialog.runs
            ScrollBar.vertical: ScrollBar {}

            delegate: Column {
                id: runRow
                required property var modelData
                property bool expanded: false
                width: historyList.width - 14
                spacing: 2
                Label {
                    width: parent.width
                    text: dialog.timestamp(modelData.finished_at) + " · " + modelData.source + " · " +
                        modelData.keyword + " · " + dialog.statusLabel(modelData.status) + " · " + modelData.rows_found + " baris"
                    elide: Text.ElideRight
                }
                RowLayout {
                    width: parent.width
                    visible: !!runRow.modelData.error
                    Label {
                        Layout.fillWidth: true
                        text: dialog.errorSummary(runRow.modelData)
                        textFormat: Text.PlainText
                        color: "#fca5a5"
                        elide: Text.ElideRight
                    }
                    ToolButton {
                        text: runRow.expanded ? "Tutup detail" : "Detail"
                        onClicked: runRow.expanded = !runRow.expanded
                    }
                }
                Label {
                    width: parent.width
                    visible: runRow.expanded
                    text: runRow.expanded ? runRow.modelData.error : ""
                    textFormat: Text.PlainText
                    color: "#fca5a5"
                    wrapMode: Text.Wrap
                }
            }
            Label {
                anchors.centerIn: parent
                visible: historyList.count === 0
                text: "Belum ada eksekusi."
                color: "#94a3b8"
            }
        }
        Button { Layout.alignment: Qt.AlignRight; text: "Tutup"; onClicked: dialog.close() }
    }

    Dialog {
        id: deletePrompt
        parent: Overlay.overlay
        anchors.centerIn: parent
        title: "Hapus jadwal ini?"
        modal: true
        standardButtons: Dialog.Yes | Dialog.No
        onAccepted: dialog.report(dialog.controller.deleteJob(dialog.selectedId), "Jadwal dihapus.")
    }
}
