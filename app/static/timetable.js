// OpenSRM Timetable Editor — drag-and-drop with mobile touch support
(function() {
    'use strict';

    var SLOTS = [
        {period:1, start:'09:30', end:'10:20', type:'class'},
        {period:2, start:'10:20', end:'11:10', type:'class'},
        {period:0, start:'11:10', end:'11:20', type:'break', name:'Break'},
        {period:3, start:'11:20', end:'12:10', type:'class'},
        {period:4, start:'12:10', end:'13:00', type:'class'},
        {period:0, start:'13:00', end:'14:10', type:'break', name:'Lunch'},
        {period:5, start:'14:10', end:'15:00', type:'class'},
        {period:6, start:'15:00', end:'15:50', type:'class'},
        {period:0, start:'15:50', end:'16:00', type:'break', name:'Break'},
        {period:7, start:'16:00', end:'16:50', type:'class'}
    ];
    var DAYS = ['Monday','Tuesday','Wednesday','Thursday','Friday'];

    var editorState = {};  // 'day-period': {code, name}
    var subjects = [];
    var groupKey = null;

    function init() {
        var btn = document.getElementById('tt-edit-btn');
        if (btn) btn.addEventListener('click', openEditor);

        var saveBtn = document.getElementById('tt-save-btn');
        if (saveBtn) saveBtn.addEventListener('click', saveTimetable);

        var cancelBtn = document.getElementById('tt-cancel-btn');
        if (cancelBtn) cancelBtn.addEventListener('click', closeEditor);

        var addBtn = document.getElementById('tt-add-subject-btn');
        if (addBtn) addBtn.addEventListener('click', showAddSubject);
    }

    function openEditor() {
        document.getElementById('tab-timetable-view').style.display = 'none';
        document.getElementById('tt-edit-btn').style.display = 'none';
        document.getElementById('tt-editor').style.display = 'block';

        // Load current timetable
        fetch('/api/timetable', {credentials: 'same-origin'})
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (!data.ok) return;
                groupKey = data.group_key;
                subjects = data.subjects || [];
                editorState = {};

                // Convert slots to editor state
                var slots = data.slots || {};
                for (var key in slots) {
                    if (slots[key] && slots[key].code) {
                        editorState[key] = slots[key];
                    }
                }

                renderPalette();
                renderGrid();
            });
    }

    function closeEditor() {
        document.getElementById('tab-timetable-view').style.display = '';
        document.getElementById('tt-edit-btn').style.display = '';
        document.getElementById('tt-editor').style.display = 'none';
    }

    function renderPalette() {
        var el = document.getElementById('tt-palette');
        el.innerHTML = '';
        subjects.forEach(function(s) {
            var block = document.createElement('div');
            block.className = 'tt-subject-block';
            block.draggable = true;
            block.dataset.code = s.code;
            block.dataset.name = s.name;
            block.innerHTML = '<span class="tt-subject-code">' + s.code + '</span>' +
                              '<span class="tt-subject-name">' + s.name + '</span>';

            block.addEventListener('dragstart', function(e) {
                e.dataTransfer.setData('text/plain', JSON.stringify({code: s.code, name: s.name}));
                e.dataTransfer.effectAllowed = 'copy';
                block.classList.add('dragging');
            });
            block.addEventListener('dragend', function() {
                block.classList.remove('dragging');
            });

            el.appendChild(block);
        });
    }

    function renderGrid() {
        var grid = document.getElementById('tt-grid-body');
        grid.innerHTML = '';

        var classSlots = SLOTS.filter(function(s) { return s.type === 'class'; });

        // Header row: empty corner + time-slot labels (horizontal = time)
        var header = document.createElement('div');
        header.className = 'tt-grid-header';
        var corner = document.createElement('div');
        header.appendChild(corner);
        classSlots.forEach(function(slot) {
            var h = document.createElement('div');
            h.textContent = slot.start;
            h.title = slot.start + ' - ' + slot.end;
            h.className = 'tt-grid-time';
            header.appendChild(h);
        });
        grid.appendChild(header);

        // Vertical = days of week
        DAYS.forEach(function(day) {
            var row = document.createElement('div');
            row.className = 'tt-grid-row';

            var dayDiv = document.createElement('div');
            dayDiv.className = 'tt-grid-day';
            dayDiv.textContent = day.slice(0, 3);
            row.appendChild(dayDiv);

            classSlots.forEach(function(slot) {
                var cell = document.createElement('div');
                cell.className = 'tt-grid-cell';
                cell.dataset.day = day;
                cell.dataset.period = slot.period;

                var key = day + '-' + slot.period;
                var placed = editorState[key];
                if (placed) {
                    cell.classList.add('tt-cell-filled');
                    cell.innerHTML = '<span class="cell-code">' + placed.code + '</span>' +
                                     '<button class="cell-remove" data-key="' + key + '">&times;</button>';
                    cell.querySelector('.cell-remove').addEventListener('click', function() {
                        delete editorState[key];
                        renderGrid();
                    });
                }

                // Drop target
                cell.addEventListener('dragover', function(e) {
                    e.preventDefault();
                    e.dataTransfer.dropEffect = 'copy';
                    cell.classList.add('tt-cell-hover');
                });
                cell.addEventListener('dragleave', function() {
                    cell.classList.remove('tt-cell-hover');
                });
                cell.addEventListener('drop', function(e) {
                    e.preventDefault();
                    cell.classList.remove('tt-cell-hover');
                    var data = JSON.parse(e.dataTransfer.getData('text/plain'));
                    editorState[key] = {code: data.code, name: data.name};
                    renderGrid();
                });

                row.appendChild(cell);
            });

            grid.appendChild(row);
        });
    }

    function showAddSubject() {
        var modal = document.getElementById('add-subject-modal');
        var codeInput = document.getElementById('subj-code');
        var nameInput = document.getElementById('subj-name');
        var confirmBtn = document.getElementById('subj-confirm-btn');
        codeInput.value = '';
        nameInput.value = '';
        modal.showModal();
        codeInput.focus();

        function onConfirm() {
            var code = codeInput.value.trim().toUpperCase();
            var name = nameInput.value.trim();
            if (!code || !name) return;
            var existing = subjects.find(function(s) { return s.code === code; });
            if (existing) {
                existing.name = name;
            } else {
                subjects.push({code: code, name: name, credits: 0, custom: true});
            }
            renderPalette();
            modal.close();
            cleanup();
        }
        function cleanup() {
            confirmBtn.removeEventListener('click', onConfirm);
        }
        confirmBtn.addEventListener('click', onConfirm);
    }

    function saveTimetable() {
        if (!groupKey) {
            showError('No timetable group found. Login again to create one.');
            return;
        }

        var customSubjects = subjects.filter(function(s) { return s.custom; });

        fetch('/api/timetable', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({slots: editorState, custom_subjects: customSubjects})
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.ok) {
                closeEditor();
                location.reload();
            } else {
                showError('Save failed: ' + (data.error || 'unknown error'));
            }
        })
        .catch(function(err) {
            showError('Save failed: ' + err.message);
        });
    }

    // Initialize when DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
