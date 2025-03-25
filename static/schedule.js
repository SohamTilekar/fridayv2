// schedule.js

function getRandomColor() {
    let color = '#000000';
    while (!isValidColor(color)) {
        color = '#' + Math.floor(Math.random() * 16777215).toString(16).padStart(6, '0');
    }
    return color;
}

function isValidColor(color) {
    // Convert hex color to RGB
    const r = parseInt(color.slice(1, 3), 16);
    const g = parseInt(color.slice(3, 5), 16);
    const b = parseInt(color.slice(5, 7), 16);

    // Define your color range restrictions here
    const minBrightness = 50; // Adjust as needed
    const maxBrightness = 200; // Adjust as needed
    const brightness = (r + g + b) / 3;

    // Example restrictions:
    if (brightness < minBrightness || brightness > maxBrightness) {
        return false; // Reject colors that are too dark or too light
    }

    // Add more restrictions as needed (e.g., avoid certain hues)
    // Example: Avoid very saturated colors
    const maxSaturation = 150; // Adjust as needed
    const maxDiff = Math.max(r, g, b) - Math.min(r, g, b);
    if (maxDiff > maxSaturation) {
        return false; // Reject very saturated colors
    }

    return true; // Color is valid
}

// --- Global variable to store the schedule ---
let fridaySchedule = { tasks: [] };
const notPlannedTasksList = document.getElementById('not-planned-tasks');
const plannedTasksList = document.getElementById('planned-tasks');
let calendar; // Declare calendar variable globally


// --- Socket.IO event handlers ---
socket.on("schedule_update", (scheduleData) => {
    fridaySchedule = scheduleData;
    updateCalendar(); // Update the calendar with the new data
    populateTaskLists(); //  Populate the task lists
});

socket.on("schedule_error", (error) => {
    console.error("Schedule error:", error);
    alert("An error occurred while updating the schedule: " + error);
});

// --- Helper function to convert schedule tasks to FullCalendar events ---
function scheduleToEvents(schedule) {
    return schedule.tasks.map(task => ({
        id: task.id,
        title: task.title,
        start: task.start,
        end: task.end,
        allDay: task.allDay,
        backgroundColor: task.backgroundColor,
        borderColor: task.borderColor,
    }));
}


// --- Modified updateCalendar function ---
function updateCalendar() {
    if (calendar) {
        // Efficiently update events using FullCalendar's API
        calendar.removeAllEventSources(); // Remove existing event sources
        calendar.addEventSource(scheduleToEvents(fridaySchedule)); // Add new source
    }
}



// --- Modified extractTaskData function ---
function extractTaskData() {
    const plannedTasksList = document.getElementById('planned-tasks');
    return Array.from(plannedTasksList.children).map(item => {
        const plannedDetails = item.querySelector('.planned-details');
        const startDateInput = plannedDetails?.querySelector('input[name="start-date"]');
        const startTimeInput = plannedDetails?.querySelector('input[name="start-time"]');
        const endDateInput = plannedDetails?.querySelector('input[name="end-date"]');
        const endTimeInput = plannedDetails?.querySelector('input[name="end-time"]');
        const colorInput = plannedDetails?.querySelector('input[name="color"]');

        const startDate = startDateInput?.value;
        const startTime = startTimeInput?.value;
        const endDate = endDateInput?.value;
        const endTime = endTimeInput?.value;
        const color = colorInput?.value;

        if (startDate) {
            const start = startTime ? startDate + 'T' + startTime : startDate;
            const end = endDate ? (endTime ? endDate + 'T' + endTime : endDate) : null;
            const taskId = item.id; //  Get existing ID

            return {
                id: taskId,
                title: item.textContent.replace(plannedDetails ? plannedDetails.textContent : '', '').trim(),
                start: start,
                end: end,
                allDay: !(startTime || endTime),
                backgroundColor: color,
                borderColor: color
            };
        } else {
            return null;
        }
    }).filter(task => task !== null);
}


// --- Modified renderCalendar function ---
function renderCalendar() {
    var calendarEl = document.getElementById('calendar');
    if (calendarEl) {
        calendar = new FullCalendar.Calendar(calendarEl, {
            initialView: 'dayGridMonth',
            dateClick: function (info) {
                calendar.changeView('timeGridDay', info.dateStr);
            },
            headerToolbar: {
                left: 'prev,next today',
                center: 'title',
                right: 'dayGridMonth,dayGridWeek,timeGridDay'
            },
            height: 'auto',
            events: scheduleToEvents(fridaySchedule), // Use the schedule data
        });
        calendar.render();
    }
}

// --- Helper function to create labels ---
function createLabel(text) {
    const label = document.createElement('label');
    label.textContent = text;
    label.classList.add('form-label', 'form-label-sm');
    return label;
}

// --- Modified addTask function ---
function addTask(section) {
    const newTaskInput = document.getElementById('new-task');
    const taskText = newTaskInput.value.trim();
    if (taskText !== '') {
        const taskItem = document.createElement('li');
        taskItem.classList.add('list-group-item');
        const taskId = 'task-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9); // Generate unique ID
        taskItem.id = taskId;
        taskItem.textContent = taskText;

        if (section === 'planned') {
            const plannedDetails = document.createElement('div');
            plannedDetails.classList.add('planned-details');

            const startDateInput = document.createElement('input');
            startDateInput.type = 'date';
            startDateInput.classList.add('form-control', 'form-control-sm');
            startDateInput.name = 'start-date';

            const startTimeInput = document.createElement('input');
            startTimeInput.type = 'time';
            startTimeInput.classList.add('form-control', 'form-control-sm');
            startTimeInput.name = 'start-time';

            const endDateInput = document.createElement('input');
            endDateInput.type = 'date';
            endDateInput.classList.add('form-control', 'form-control-sm');
            endDateInput.name = 'end-date';

            const endTimeInput = document.createElement('input');
            endTimeInput.type = 'time';
            endTimeInput.classList.add('form-control', 'form-control-sm');
            endTimeInput.name = 'end-time';

            const colorInput = document.createElement('input');
            colorInput.type = 'color';
            colorInput.classList.add('form-control', 'form-control-sm');
            colorInput.name = 'color';
            colorInput.value = getRandomColor(); // Default color

            const toggleButton = document.createElement('button');
            toggleButton.innerHTML = '<i class="bi bi-pencil-square"></i>'; // Edit icon
            toggleButton.classList.add('btn', 'btn-outline-secondary', 'btn-sm', 'toggle-icon');
            toggleButton.addEventListener('click', function (event) {
                detailsContainer.classList.toggle('d-none');
                event.stopPropagation(); // Prevent triggering taskItem click
            });

            const detailsContainer = document.createElement('div');
            detailsContainer.classList.add('details-container', 'd-none'); // Initially hidden

            detailsContainer.appendChild(createLabel('Start Date:'));
            detailsContainer.appendChild(startDateInput);
            detailsContainer.appendChild(createLabel('Start Time:'));
            detailsContainer.appendChild(startTimeInput);
            detailsContainer.appendChild(createLabel('End Date:'));
            detailsContainer.appendChild(endDateInput);
            detailsContainer.appendChild(createLabel('End Time:'));
            detailsContainer.appendChild(endTimeInput);
            detailsContainer.appendChild(createLabel('Color:'));
            detailsContainer.appendChild(colorInput);

            plannedDetails.appendChild(toggleButton);
            plannedDetails.appendChild(detailsContainer);
            taskItem.appendChild(plannedDetails);

            // --- Event listeners for input changes (moved here) ---
            function updateCalendarEvent() {
                const taskData = extractTaskData().find(t => t.id === taskId); // Get updated data
                if (taskData) {
                    socket.emit("update_task", taskData); // Send updated task to server
                }
            }

            startDateInput.addEventListener('change', updateCalendarEvent);
            startTimeInput.addEventListener('change', updateCalendarEvent);
            endDateInput.addEventListener('change', updateCalendarEvent);
            endTimeInput.addEventListener('change', updateCalendarEvent);
            colorInput.addEventListener('change', updateCalendarEvent);

            plannedTasksList.appendChild(taskItem);
            // --- Emit add_task event with the new task data ---
            const newTaskData = extractTaskData().find(t => t.id === taskId);
            if (newTaskData) {
                socket.emit("add_task", newTaskData);
            }

        } else {
            notPlannedTasksList.appendChild(taskItem);
             // --- Emit add_task event with the new task data ---
            const newTaskData = {
                id: taskId,
                title: taskText,
                start: null,
                end: null,
                allDay: true,
                backgroundColor: null,
                borderColor: null
            };
            socket.emit("add_task", newTaskData);
        }

        newTaskInput.value = '';
    }
}


// --- SortableJS onAdd handlers (simplified and refactored) ---

function handleTaskMove(evt) {
    const item = evt.item;
    const plannedDetails = item.querySelector('.planned-details');
    const targetList = evt.to.id; // 'planned-tasks', 'not-planned-tasks', or 'done-tasks'
    const sourceList = evt.from.id;
    if (sourceList === 'done-tasks')
        socket.emit("reopen_task", item.id);
    if (targetList === 'planned-tasks') {
        // Add planned details if they don't exist
        if (!plannedDetails) {
            const plannedDetails = document.createElement('div');
            plannedDetails.classList.add('planned-details');

            const startDateInput = document.createElement('input');
            startDateInput.type = 'date';
            startDateInput.classList.add('form-control', 'form-control-sm');
            startDateInput.name = 'start-date';

            const startTimeInput = document.createElement('input');
            startTimeInput.type = 'time';
            startTimeInput.classList.add('form-control', 'form-control-sm');
            startTimeInput.name = 'start-time';

            const endDateInput = document.createElement('input');
            endDateInput.type = 'date';
            endDateInput.classList.add('form-control', 'form-control-sm');
            endDateInput.name = 'end-date';

            const endTimeInput = document.createElement('input');
            endTimeInput.type = 'time';
            endTimeInput.classList.add('form-control', 'form-control-sm');
            endTimeInput.name = 'end-time';

            const colorInput = document.createElement('input');
            colorInput.type = 'color';
            colorInput.classList.add('form-control', 'form-control-sm');
            colorInput.name = 'color';
            colorInput.value = getRandomColor(); // Default color

            const toggleButton = document.createElement('button');
            toggleButton.innerHTML = '<i class="bi bi-pencil-square"></i>'; // Edit icon
            toggleButton.classList.add('btn', 'btn-outline-secondary', 'btn-sm', 'toggle-icon');
            toggleButton.addEventListener('click', function (event) {
                detailsContainer.classList.toggle('d-none');
                event.stopPropagation(); // Prevent triggering taskItem click
            });
            
            const detailsContainer = document.createElement('div');
            detailsContainer.classList.add('details-container', 'd-none'); // Initially hidden

            detailsContainer.appendChild(createLabel('Start Date:'));
            detailsContainer.appendChild(startDateInput);
            detailsContainer.appendChild(createLabel('Start Time:'));
            detailsContainer.appendChild(startTimeInput);
            detailsContainer.appendChild(createLabel('End Date:'));
            detailsContainer.appendChild(endDateInput);
            detailsContainer.appendChild(createLabel('End Time:'));
            detailsContainer.appendChild(endTimeInput);
            detailsContainer.appendChild(createLabel('Color:'));
            detailsContainer.appendChild(colorInput);

            plannedDetails.appendChild(toggleButton);
            plannedDetails.appendChild(detailsContainer);
            item.appendChild(plannedDetails);
            
            // --- Event listeners for input changes (moved here) ---
            function updateCalendarEvent() {
                const taskData = extractTaskData().find(t => t.id === item.id); // Get updated data
                if (taskData) {
                    socket.emit("update_task", taskData); // Send updated task to server
                }
            }

            startDateInput.addEventListener('change', updateCalendarEvent);
            startTimeInput.addEventListener('change', updateCalendarEvent);
            endDateInput.addEventListener('change', updateCalendarEvent);
            endTimeInput.addEventListener('change', updateCalendarEvent);
            colorInput.addEventListener('change', updateCalendarEvent);
        }
        // if it have the planned details then update the task
        else {
            const taskData = extractTaskData().find(t => t.id === item.id); // Get updated data
            if (taskData) {
                socket.emit("update_task", taskData); // Send updated task to server
            }
        }
    } else if (targetList === 'not-planned-tasks') {
        // Remove planned details
        if (plannedDetails) {
            item.removeChild(plannedDetails);
        }
        // Update task on server to remove planning details
        socket.emit("update_task", {
            id: item.id,
            title: item.textContent,
            start: null,
            end: null,
            allDay: true,
            backgroundColor: null,
            borderColor: null
        });
    }
    else if (targetList === 'done-tasks') {
        // Remove planned details
        if (plannedDetails) {
            item.removeChild(plannedDetails);
        }
        // Update task on server to mark as complete
        socket.emit("complete_task", item.id);
    }
}

function updateScrollableContentHeight() {
    const schedulePane = document.getElementById('schedule-pane');
    const scrollableContent = document.querySelector('.scrollable-content');

    if (schedulePane && scrollableContent) {
        const availableHeight = schedulePane.offsetHeight;
        scrollableContent.style.maxHeight = availableHeight + 'px';
    }
}

// --- Populate Task Lists ---

function populateTaskLists() {
    const notPlannedTasksList = document.getElementById('not-planned-tasks');
    const plannedTasksList = document.getElementById('planned-tasks');
    const doneTasksList = document.getElementById('done-tasks'); // Get the "Done" list

    // Clear existing lists
    notPlannedTasksList.innerHTML = '';
    plannedTasksList.innerHTML = '';
    doneTasksList.innerHTML = ''; // Clear the "Done" list

    fridaySchedule.tasks.forEach(task => {
        const taskItem = document.createElement('li');
        taskItem.classList.add('list-group-item', 'justify-content-between', 'align-items-center'); // Add flex classes
        taskItem.id = task.id;
        taskItem.textContent = task.title;

        if (task.completed) { // If task is completed
            const deleteButton = document.createElement('button');
            deleteButton.classList.add('delete-file-button'); // Use existing delete button style
            deleteButton.innerHTML = '<i class="bi bi-x"></i>';
            deleteButton.addEventListener('click', (event) => {
                event.stopPropagation(); // Prevent SortableJS from catching the click
                socket.emit("delete_task", task.id);
            });

            taskItem.appendChild(deleteButton); // Add delete button to task item
            doneTasksList.appendChild(taskItem);
        }
        else if (task.start) { // If task has a start date, it's planned
            const plannedDetails = document.createElement('div');
            plannedDetails.classList.add('planned-details');

            const startDateInput = document.createElement('input');
            startDateInput.type = 'date';
            startDateInput.classList.add('form-control', 'form-control-sm');
            startDateInput.name = 'start-date';
            startDateInput.value = task.start.split('T')[0]; // Extract date part

            const startTimeInput = document.createElement('input');
            startTimeInput.type = 'time';
            startTimeInput.classList.add('form-control', 'form-control-sm');
            startTimeInput.name = 'start-time';
            if (task.start.includes('T')) {
                startTimeInput.value = task.start.split('T')[1]; // Extract time part
            }

            const endDateInput = document.createElement('input');
            endDateInput.type = 'date';
            endDateInput.classList.add('form-control', 'form-control-sm');
            endDateInput.name = 'end-date';
            if (task.end) {
                endDateInput.value = task.end.split('T')[0];
            }

            const endTimeInput = document.createElement('input');
            endTimeInput.type = 'time';
            endTimeInput.classList.add('form-control', 'form-control-sm');
            endTimeInput.name = 'end-time';
            if (task.end && task.end.includes('T')) {
                endTimeInput.value = task.end.split('T')[1];
            }

            const colorInput = document.createElement('input');
            colorInput.type = 'color';
            colorInput.classList.add('form-control', 'form-control-sm');
            colorInput.name = 'color';
            colorInput.value = task.backgroundColor || getRandomColor();

            const toggleButton = document.createElement('button');
            toggleButton.innerHTML = '<i class="bi bi-pencil-square"></i>';
            toggleButton.classList.add('btn', 'btn-outline-secondary', 'btn-sm', 'toggle-icon');
            const detailsContainer = document.createElement('div'); //  Declare detailsContainer
            toggleButton.addEventListener('click', function (event) {
                detailsContainer.classList.toggle('d-none');
                event.stopPropagation();
            });


            detailsContainer.classList.add('details-container', 'd-none');

            detailsContainer.appendChild(createLabel('Start Date:'));
            detailsContainer.appendChild(startDateInput);
            detailsContainer.appendChild(createLabel('Start Time:'));
            detailsContainer.appendChild(startTimeInput);
            detailsContainer.appendChild(createLabel('End Date:'));
            detailsContainer.appendChild(endDateInput);
            detailsContainer.appendChild(createLabel('End Time:'));
            detailsContainer.appendChild(endTimeInput);
            detailsContainer.appendChild(createLabel('Color:'));
            detailsContainer.appendChild(colorInput);

            plannedDetails.appendChild(toggleButton);
            plannedDetails.appendChild(detailsContainer);
            taskItem.appendChild(plannedDetails);

            // --- Event listeners for input changes ---
            function updateCalendarEvent() {
                const taskData = extractTaskData().find(t => t.id === task.id);
                if (taskData) {
                    socket.emit("update_task", taskData);
                }
            }

            startDateInput.addEventListener('change', updateCalendarEvent);
            startTimeInput.addEventListener('change', updateCalendarEvent);
            endDateInput.addEventListener('change', updateCalendarEvent);
            endTimeInput.addEventListener('change', updateCalendarEvent);
            colorInput.addEventListener('change', updateCalendarEvent);

            plannedTasksList.appendChild(taskItem);

        } else {
            // Task is not planned
            notPlannedTasksList.appendChild(taskItem);
        }
    });
}

// --- Initialization ---

document.addEventListener('DOMContentLoaded', function () {
    const notPlannedTasksList = document.getElementById('not-planned-tasks');
    const plannedTasksList = document.getElementById('planned-tasks');
    const doneTasksList = document.getElementById('done-tasks'); // Get the "Done" list
    const newTaskInput = document.getElementById('new-task');

    new Sortable(notPlannedTasksList, {
        group: 'shared',
        animation: 150,
        onAdd: handleTaskMove,
    });

    new Sortable(plannedTasksList, {
        group: 'shared',
        animation: 150,
        onAdd: handleTaskMove,
    });

    new Sortable(doneTasksList, { // Initialize SortableJS for the "Done" list
        group: 'shared',
        animation: 150,
        onAdd: handleTaskMove,
    });

    // Fetch initial schedule from server
    socket.emit("get_schedule");

    // Initialize calendar when the schedule tab is shown
    var scheduleTabEl = document.getElementById('schedule-tab');
    if (scheduleTabEl) {
        scheduleTabEl.addEventListener('shown.bs.tab', function (event) {
            if (!calendar) {
                renderCalendar([]); // Render with an empty array initially
            } else {
                calendar.updateSize(); // Use updateSize() instead of destroy/render
            }
            updateScrollableContentHeight();
        });
    }

    // Recalculate calendar size on right panel resize
    const rightPanel = document.querySelector('.right-panel');
    if (rightPanel) {
        const resizeObserver = new ResizeObserver(entries => {
            if (calendar) {
                calendar.updateSize(); // Use updateSize()
            }
            updateScrollableContentHeight();
        });
        resizeObserver.observe(rightPanel);
    }

    // Add event listener for adding tasks with Enter key in newTaskInput
    newTaskInput.addEventListener('keydown', function (event) {
        if (event.key === 'Enter') {
            addTask('not-planned'); // Add to not-planned by default
            event.preventDefault();
        }
    });

    // Initial call and window resize listener for scrollable content height
    updateScrollableContentHeight();
    window.addEventListener('resize', updateScrollableContentHeight);
});
