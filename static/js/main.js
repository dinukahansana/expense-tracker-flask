/**
 * Expense Tracker Application
 * Main JavaScript file handling frontend interaction logic.
 */

// Global state for selected expense
let selectedExpense = null; // { id, name }

/**
 * Mobile Navigation Toggle
 * Handles opening and closing the mobile navbar menu.
 */
function initMobileNav() {
  const navToggle = document.getElementById('navbar-toggle');
  const navMenu = document.getElementById('navbar-menu');
  
  if (navToggle && navMenu) {
    navToggle.addEventListener('click', () => {
      navMenu.classList.toggle('open');
    });
    
    // Close menu when clicking a link
    navMenu.querySelectorAll('.nav-link').forEach(link => {
      link.addEventListener('click', () => navMenu.classList.remove('open'));
    });
  }
}

/**
 * Expense Selection System
 * Handles selecting expenses via radio buttons or row clicks.
 */
function initExpenseSelection() {
  const rows = document.querySelectorAll('.expense-row');
  const radios = document.querySelectorAll('.expense-radio');
  
  if (!rows.length) return;
  
  // Handle clicking on the entire row
  rows.forEach(row => {
    row.addEventListener('click', (e) => {
      // Don't interfere with radio click itself
      if (e.target.classList.contains('expense-radio')) return;
      
      const radio = row.querySelector('.expense-radio');
      if (radio) {
        radio.checked = true;
        handleSelection(radio);
      }
    });
  });
  
  // Handle radio button changes directly
  radios.forEach(radio => {
    radio.addEventListener('change', () => handleSelection(radio));
  });
}

/**
 * Process selection of a specific expense
 * @param {HTMLInputElement} radio The selected radio input element
 */
function handleSelection(radio) {
  // Deselect all rows
  document.querySelectorAll('.expense-row').forEach(r => r.classList.remove('selected'));
  
  // Select this row
  radio.closest('.expense-row').classList.add('selected');
  
  // Update global state
  selectedExpense = {
    id: radio.dataset.id,
    name: radio.dataset.name
  };
  
  // Update info display
  const info = document.getElementById('selected-expense-info');
  if (info) {
    info.innerHTML = 'Selected: <strong>' + escapeHtml(selectedExpense.name) + '</strong>';
  }
}

/**
 * Action Dropdown System
 * Handles the dropdown menu for Edit and Delete actions.
 */
function initActionDropdown() {
  const dropdownBtn = document.getElementById('action-dropdown-btn');
  const dropdownMenu = document.getElementById('action-dropdown-menu');
  
  if (!dropdownBtn || !dropdownMenu) return;
  
  // Toggle dropdown on button click
  dropdownBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    dropdownMenu.classList.toggle('open');
  });
  
  // Close dropdown when clicking outside
  document.addEventListener('click', () => {
    dropdownMenu.classList.remove('open');
  });
  
  // Edit action
  const editBtn = document.getElementById('action-edit');
  if (editBtn) {
    editBtn.addEventListener('click', () => {
      if (!selectedExpense) {
        showToast('Please select an expense first.', 'warning');
        return;
      }
      window.location.href = '/edit/' + selectedExpense.id;
    });
  }
  
  // Delete action
  const deleteBtn = document.getElementById('action-delete');
  if (deleteBtn) {
    deleteBtn.addEventListener('click', () => {
      if (!selectedExpense) {
        showToast('Please select an expense first.', 'warning');
        return;
      }
      openDeleteModal(selectedExpense.id, selectedExpense.name);
    });
  }
}

/**
 * Delete Confirmation Modal
 * Handles opening the modal and setting up the dynamic deletion form.
 */
function openDeleteModal(id, name) {
  const overlay = document.getElementById('delete-modal');
  const expenseName = document.getElementById('delete-expense-name');
  const confirmBtn = document.getElementById('delete-confirm-btn');
  
  if (!overlay) return;
  
  if (expenseName) {
    expenseName.textContent = '"' + name + '"';
  }
  
  overlay.classList.add('open');
  
  // Set up confirm handler (clone to remove old listeners)
  const newConfirmBtn = confirmBtn.cloneNode(true);
  confirmBtn.parentNode.replaceChild(newConfirmBtn, confirmBtn);
  newConfirmBtn.id = 'delete-confirm-btn';
  
  newConfirmBtn.addEventListener('click', () => {
    // Create and submit a POST form to /delete/<id>
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '/delete/' + id;
    const csrf = document.createElement('input');
    csrf.type = 'hidden';
    csrf.name = 'csrf_token';
    csrf.value = document.querySelector('meta[name="csrf-token"]').content;
    form.appendChild(csrf);
    document.body.appendChild(form);
    form.submit();
  });
}

/**
 * Close Delete Modal
 */
function closeDeleteModal() {
  const overlay = document.getElementById('delete-modal');
  if (overlay) {
    overlay.classList.remove('open');
  }
}

/**
 * Toast Notification System
 * Displays a temporary toast notification message.
 * 
 * @param {string} message - The message to display
 * @param {string} type - 'success', 'error', or 'warning'
 */
function showToast(message, type = 'success') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  
  const toast = document.createElement('div');
  toast.className = 'toast ' + type;
  
  // Prepare icon SVG based on type
  let iconSvg = '';
  if (type === 'success') {
    iconSvg = '<i data-lucide="check-circle" class="toast-icon"></i>';
  } else if (type === 'error') {
    iconSvg = '<i data-lucide="x-circle" class="toast-icon"></i>';
  } else if (type === 'warning') {
    iconSvg = '<i data-lucide="alert-triangle" class="toast-icon"></i>';
  }
  
  // Construct toast HTML
  toast.innerHTML = iconSvg + 
    '<span class="toast-message">' + escapeHtml(message) + '</span>' +
    '<button class="toast-close" onclick="this.parentElement.remove()">' +
    '<i data-lucide="x"></i></button>';
  
  container.appendChild(toast);
  
  // Re-initialize lucide icons for new elements
  if (window.lucide) {
    lucide.createIcons();
  }
  
  // Trigger animation (requestAnimationFrame ensures DOM registers the element first)
  requestAnimationFrame(() => {
    toast.classList.add('show');
  });
  
  // Auto-remove after 4 seconds
  setTimeout(() => {
    toast.classList.remove('show');
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

/**
 * Helper to escape HTML to prevent XSS
 */
function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

/**
 * Theme Toggle (Dark Mode / Light Mode)
 * Reads preference from localStorage, falls back to system preference.
 * Toggles data-theme attribute on <html> and persists choice.
 */
function initThemeToggle() {
  const toggleBtns = document.querySelectorAll('.theme-toggle');
  if (!toggleBtns.length) return;

  toggleBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const currentTheme = document.documentElement.getAttribute('data-theme');
      const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
      applyTheme(newTheme);
      localStorage.setItem('expense-tracker-theme', newTheme);
    });
  });
}

/**
 * Apply a theme to the document
 * @param {string} theme - 'light' or 'dark'
 */
function applyTheme(theme) {
  if (theme === 'dark') {
    document.documentElement.setAttribute('data-theme', 'dark');
  } else {
    document.documentElement.removeAttribute('data-theme');
  }
}

/**
 * Get the user's preferred theme.
 * Priority: localStorage > system preference > light
 * @returns {string} 'light' or 'dark'
 */
function getPreferredTheme() {
  const stored = localStorage.getItem('expense-tracker-theme');
  if (stored) return stored;
  if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
    return 'dark';
  }
  return 'light';
}

/**
 * Initialize application on DOM content loaded
 */
document.addEventListener('DOMContentLoaded', () => {
  initMobileNav();
  initExpenseSelection();
  initActionDropdown();
  initThemeToggle();
  
  // Initialize Lucide icons
  if (window.lucide) {
    lucide.createIcons();
  }
  
  // Close modal on overlay click
  const deleteModal = document.getElementById('delete-modal');
  if (deleteModal) {
    deleteModal.addEventListener('click', (e) => {
      if (e.target === deleteModal) {
        closeDeleteModal();
      }
    });
  }
  
  // Close modal on cancel button
  const cancelBtn = document.getElementById('delete-cancel-btn');
  if (cancelBtn) {
    cancelBtn.addEventListener('click', closeDeleteModal);
  }
  
  // Escape key closes modal and dropdown
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeDeleteModal();
      const dropdownMenu = document.getElementById('action-dropdown-menu');
      if (dropdownMenu) dropdownMenu.classList.remove('open');
    }
  });
});
