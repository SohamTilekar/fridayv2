function getRandomColor() {
  let color = '#000000';
  while (!isValidColor(color)) {
    color = '#' + Math.floor(Math.random()*16777215).toString(16).padStart(6, '0');
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

document.addEventListener('DOMContentLoaded', function() {
  var calendar; // Declare calendar variable
  var calendarEvents = []; // Store events to preserve colors on resize

  function renderCalendar(tasks) {
    var calendarEl = document.getElementById('calendar');
    if (calendarEl) {
      calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth',
        dateClick: function(info) {
          calendar.changeView('timeGridDay', info.dateStr); // Switch to timeGridDay view
        },
        headerToolbar: {
          left: 'prev,next today',
          center: 'title',
          right: 'dayGridMonth,dayGridWeek,timeGridDay'
        },
        height: 'auto',
        events: calendarEvents.length > 0 ? calendarEvents : tasks // Use stored events if available
      });
      calendar.render();
      
      // If this is the first render, store the initial events
      if (calendarEvents.length === 0 && tasks.length > 0) {
        calendarEvents = [...tasks];
      }
    }
  }

  // Helper function to extract task data
  function extractTaskData() {
    const plannedTasksList = document.getElementById('planned-tasks');
    return Array.from(plannedTasksList.children).map(item => {
      const plannedDetails = item.querySelector('.planned-details');
      const startDateInput = plannedDetails ? plannedDetails.querySelector('input[name="start-date"]') : null;
      const startTimeInput = plannedDetails ? plannedDetails.querySelector('input[name="start-time"]') : null;
      const endDateInput = plannedDetails ? plannedDetails.querySelector('input[name="end-date"]') : null;
      const endTimeInput = plannedDetails ? plannedDetails.querySelector('input[name="end-time"]') : null;
      const colorInput = plannedDetails ? plannedDetails.querySelector('input[name="color"]') : null;

      const startDate = startDateInput ? startDateInput.value : null;
      const startTime = startTimeInput ? startTimeInput.value : null;
      const endDate = endDateInput ? endDateInput.value : null;
      const endTime = endTimeInput ? endTimeInput.value : null;
      const color = colorInput ? colorInput.value : null;

      if (startDate) {
        const start = startTime ? startDate + 'T' + startTime : startDate;
        const end = endDate ? (endTime ? endDate + 'T' + endTime : endDate) : null;
        
        // Store the DOM element ID to track tasks
        const taskId = item.id || ('task-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9));
        if (!item.id) {
          item.id = taskId;
        }

        return {
          id: taskId, // Add unique ID for tracking
          title: item.textContent.replace(plannedDetails ? plannedDetails.textContent : '', '').trim(), // Task title
          start: start,
          end: end,
          allDay: !(startTime || endTime), // Set allDay to true if time is not available
          backgroundColor: color, // Set the background color directly
          borderColor: color     // Set the border color to match
        };
      } else {
        return null;
      }
    }).filter(task => task !== null);
  }

  // Initialize calendar when the schedule tab is shown
  var scheduleTabEl = document.getElementById('schedule-tab');
  if (scheduleTabEl) {
    scheduleTabEl.addEventListener('shown.bs.tab', function (event) {
      // Fetch tasks from the "Planned" list
      const tasks = extractTaskData();
      
      if (!calendar) { // Check if calendar is already initialized
        renderCalendar(tasks);
      } else {
        calendar.destroy(); // Destroy the existing calendar
        renderCalendar(tasks); // Re-render the calendar
      }
      updateScrollableContentHeight(); // Update scrollable content height
    });
  }

  // Function to update calendar with current task data
  function updateCalendar() {
    if (calendar) {
      const tasks = extractTaskData();
      calendarEvents = tasks; // Update stored events
      
      // Remove all events and add the updated ones
      calendar.removeAllEvents();
      tasks.forEach(task => {
        calendar.addEvent(task);
      });
    }
  }

  // Recalculate calendar size on right panel resize
  const rightPanel = document.querySelector('.right-panel');
  if (rightPanel) {
    const resizeObserver = new ResizeObserver(entries => {
      if (calendar) {
        calendar.destroy(); // Destroy the existing calendar
        renderCalendar([]); // Re-render the calendar with stored events
      }
      updateScrollableContentHeight(); // Update scrollable content height
    });
    resizeObserver.observe(rightPanel);
  }

  // To-Do List Functionality
  const newTaskInput = document.getElementById('new-task');
  const notPlannedTasksList = document.getElementById('not-planned-tasks');
  const plannedTasksList = document.getElementById('planned-tasks');

  function addTask(section) {
    const taskText = newTaskInput.value.trim();
    if (taskText !== '') {
      const taskItem = document.createElement('li');
      taskItem.classList.add('list-group-item');
      // Assign a unique ID to each task
      taskItem.id = 'task-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
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
        toggleButton.addEventListener('click', function(event) {
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

        // Link to calendar
        function updateCalendarEvent() {
          const startDate = startDateInput.value;
          const startTime = startTimeInput.value;
          const endDate = endDateInput.value;
          const endTime = endTimeInput.value;
          const color = colorInput.value;

          // Remove the task from stored events if it exists
          calendarEvents = calendarEvents.filter(event => event.id !== taskItem.id);

          if (startDate) {
            const start = startTime ? startDate + 'T' + startTime : startDate;
            const end = endDate ? (endTime ? endDate + 'T' + endTime : endDate) : null;
            
            // Create new event data
            const eventData = {
              id: taskItem.id,
              title: taskText,
              start: start,
              end: end,
              allDay: !(startTime || endTime),
              backgroundColor: color, // Set background color directly
              borderColor: color      // Set border color to match
            };
            
            // Add to stored events
            calendarEvents.push(eventData);
            
            // Update calendar if it exists
            if (calendar) {
              // Remove existing event if it exists
              const existingEvent = calendar.getEventById(taskItem.id);
              if (existingEvent) {
                existingEvent.remove();
              }
              
              // Add the updated event
              calendar.addEvent(eventData);
            }
          }
        }

        startDateInput.addEventListener('change', updateCalendarEvent);
        startTimeInput.addEventListener('change', updateCalendarEvent);
        endDateInput.addEventListener('change', updateCalendarEvent);
        endTimeInput.addEventListener('change', updateCalendarEvent);
        colorInput.addEventListener('change', updateCalendarEvent);
      }

      switch (section) {
        case 'not-planned':
          notPlannedTasksList.appendChild(taskItem);
          break;
        case 'planned':
          plannedTasksList.appendChild(taskItem);
          break;
        default:
          notPlannedTasksList.appendChild(taskItem); // Default to not-planned
      }

      newTaskInput.value = '';
      
      // Update calendar after adding a task if it's a planned task
      if (section === 'planned') {
        updateCalendar();
      }
    }
  }

  function createLabel(text) {
    const label = document.createElement('label');
    label.textContent = text;
    label.classList.add('form-label', 'form-label-sm');
    return label;
  }

  newTaskInput.addEventListener('keydown', function(event) {
    if (event.key === 'Enter') {
      addTask('not-planned'); // Default to not-planned section
      event.preventDefault(); // Prevent form submission
    }
  });

  // Function to update scrollable content height
  function updateScrollableContentHeight() {
    const schedulePane = document.getElementById('schedule-pane');
    const scrollableContent = document.querySelector('.scrollable-content');

    if (schedulePane && scrollableContent) {
      const availableHeight = schedulePane.offsetHeight;
      scrollableContent.style.maxHeight = availableHeight + 'px';
    }
  }

  // Initial call to set the height
  updateScrollableContentHeight();

  // Update height on window resize
  window.addEventListener('resize', updateScrollableContentHeight);

  // Initialize SortableJS for each task list
  new Sortable(notPlannedTasksList, {
    group: 'shared', // set both lists to same group
    animation: 150,
    onAdd: function (evt) {
      // When an item is moved to the "Not Planned" list, remove date and time inputs
      const item = evt.item;
      const plannedDetails = item.querySelector('.planned-details');
      
      if (plannedDetails) {
        item.removeChild(plannedDetails);
      }
      
      // Remove the task from the calendar and stored events
      if (calendar) {
        const existingEvent = calendar.getEventById(item.id);
        if (existingEvent) {
          existingEvent.remove();
        }
      }
      
      // Also remove from stored events array
      calendarEvents = calendarEvents.filter(event => event.id !== item.id);
    }
  });

  new Sortable(plannedTasksList, {
    group: 'shared',
    animation: 150,
    onAdd: function (evt) {
      // When an item is moved to the "Planned" list, add date and time inputs
      const item = evt.item;
      
      // Ensure the task has an ID
      if (!item.id) {
        item.id = 'task-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
      }
      
      if (!item.querySelector('.planned-details')) {
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
        toggleButton.addEventListener('click', function(event) {
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

        // Link to calendar
        function updateCalendarEvent() {
          const startDate = startDateInput.value;
          const startTime = startTimeInput.value;
          const endDate = endDateInput.value;
          const endTime = endTimeInput.value;
          const color = colorInput.value;

          // Remove from stored events if it exists
          calendarEvents = calendarEvents.filter(event => event.id !== item.id);

          if (startDate) {
            const start = startTime ? startDate + 'T' + startTime : startDate;
            const end = endDate ? (endTime ? endDate + 'T' + endTime : endDate) : null;
            
            // Create new event data
            const eventData = {
              id: item.id,
              title: item.textContent.replace(plannedDetails.textContent, '').trim(),
              start: start,
              end: end,
              allDay: !(startTime || endTime),
              backgroundColor: color, // Set background color directly
              borderColor: color      // Set border color to match
            };
            
            // Add to stored events
            calendarEvents.push(eventData);
            
            // Update calendar if it exists
            if (calendar) {
              // Remove existing event if it exists
              const existingEvent = calendar.getEventById(item.id);
              if (existingEvent) {
                existingEvent.remove();
              }
              
              // Add the updated event
              calendar.addEvent(eventData);
            }
          }
        }

        startDateInput.addEventListener('change', updateCalendarEvent);
        startTimeInput.addEventListener('change', updateCalendarEvent);
        endDateInput.addEventListener('change', updateCalendarEvent);
        endTimeInput.addEventListener('change', updateCalendarEvent);
        colorInput.addEventListener('change', updateCalendarEvent);
      }
    }
  });
});