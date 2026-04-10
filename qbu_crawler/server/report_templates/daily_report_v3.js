/**
 * Qbu-Crawler Daily Report V3 — Interactive UI
 * Vanilla JS, no dependencies (Chart.js loaded separately via CDN)
 * Covers: tabs, collapsible cards, evidence lightbox, table sort/filter,
 *         sticky KPI shadow, print button, Chart.js canvas init.
 */
(function () {
  'use strict';

  /* =========================================================================
     1. TAB NAVIGATION (~30 lines)
     ========================================================================= */

  function initTabs() {
    var navButtons = document.querySelectorAll('.tab-nav button[data-tab]');
    var panels = document.querySelectorAll('.tab-panel');

    function activateTab(tabId) {
      navButtons.forEach(function (btn) {
        btn.classList.toggle('tab-active', btn.getAttribute('data-tab') === tabId);
      });
      panels.forEach(function (panel) {
        panel.classList.toggle('tab-active', panel.id === 'tab-' + tabId);
      });
    }

    navButtons.forEach(function (btn) {
      btn.addEventListener('click', function () {
        activateTab(btn.getAttribute('data-tab'));
      });
    });

    // Show first tab by default
    if (navButtons.length > 0) {
      var firstTab = navButtons[0].getAttribute('data-tab');
      activateTab(firstTab);
    }
  }

  /* =========================================================================
     2. COLLAPSIBLE CARDS (~30 lines)
     ========================================================================= */

  function initCollapsible() {
    var cards = document.querySelectorAll('.issue-card');

    cards.forEach(function (card) {
      var header = card.querySelector('.card-header');
      if (!header) return;

      // Default collapsed if attribute set
      if (card.getAttribute('data-default-collapsed') === 'true') {
        card.classList.add('card-collapsed');
      }

      header.addEventListener('click', function () {
        card.classList.toggle('card-collapsed');
      });
    });
  }

  /* =========================================================================
     3. EVIDENCE LIGHTBOX (~50 lines)
     ========================================================================= */

  function initLightbox() {
    var lightbox = document.getElementById('lightbox');
    var lightboxImg = document.getElementById('lightbox-img');
    var closeBtn = document.getElementById('lightbox-close');

    if (!lightbox || !lightboxImg) return;

    function openLightbox(src, alt) {
      lightboxImg.src = src;
      lightboxImg.alt = alt || '';
      lightbox.classList.add('lightbox-open');
      document.body.style.overflow = 'hidden';
    }

    function closeLightbox() {
      lightbox.classList.remove('lightbox-open');
      lightboxImg.src = '';
      document.body.style.overflow = '';
    }

    // Clicks on .evidence-img thumbnails
    document.addEventListener('click', function (e) {
      var target = e.target;
      if (target.classList.contains('evidence-img')) {
        var src = target.getAttribute('data-full') || target.src;
        openLightbox(src, target.alt);
      }
    });

    // Close via button
    if (closeBtn) {
      closeBtn.addEventListener('click', closeLightbox);
    }

    // Close via backdrop click (but not image click)
    lightbox.addEventListener('click', function (e) {
      if (e.target === lightbox) closeLightbox();
    });

    // Escape key
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && lightbox.classList.contains('lightbox-open')) {
        closeLightbox();
      }
    });
  }

  /* =========================================================================
     4. TABLE SORT (~60 lines)
     ========================================================================= */

  function initTableSort() {
    var tables = document.querySelectorAll('.data-table');

    tables.forEach(function (table) {
      var headers = table.querySelectorAll('th[data-sortable]');

      headers.forEach(function (th) {
        // Inject sort indicator span if not present
        if (!th.querySelector('.sort-indicator')) {
          var span = document.createElement('span');
          span.className = 'sort-indicator';
          span.textContent = '⇅';
          th.appendChild(span);
        }

        th.addEventListener('click', function () {
          var isAsc = th.classList.contains('sort-asc');
          var colIdx = Array.prototype.indexOf.call(th.parentNode.children, th);

          // Reset all header states in this table
          headers.forEach(function (h) {
            h.classList.remove('sort-asc', 'sort-desc');
            var ind = h.querySelector('.sort-indicator');
            if (ind) ind.textContent = '⇅';
          });

          // Apply new sort direction
          var nextAsc = !isAsc;
          th.classList.add(nextAsc ? 'sort-asc' : 'sort-desc');
          var indicator = th.querySelector('.sort-indicator');
          if (indicator) indicator.textContent = nextAsc ? '▲' : '▼';

          // Sort rows
          var tbody = table.querySelector('tbody');
          if (!tbody) return;
          var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));

          rows.sort(function (a, b) {
            var cellA = (a.cells[colIdx] ? a.cells[colIdx].textContent.trim() : '');
            var cellB = (b.cells[colIdx] ? b.cells[colIdx].textContent.trim() : '');
            var numA = parseFloat(cellA.replace(/[^0-9.-]/g, ''));
            var numB = parseFloat(cellB.replace(/[^0-9.-]/g, ''));
            var isNumeric = !isNaN(numA) && !isNaN(numB);
            var cmp = isNumeric ? (numA - numB) : cellA.localeCompare(cellB, 'zh-CN');
            return nextAsc ? cmp : -cmp;
          });

          rows.forEach(function (row) { tbody.appendChild(row); });
        });
      });
    });
  }

  /* =========================================================================
     5. TABLE FILTER (~50 lines)
     ========================================================================= */

  function initTableFilter() {
    var filterInputs = document.querySelectorAll('.filter-input');

    filterInputs.forEach(function (input) {
      var targetId = input.getAttribute('data-target');
      var table = targetId
        ? document.getElementById(targetId)
        : input.closest('.filter-bar') && input.closest('.filter-bar').nextElementSibling;

      if (!table) return;

      var countEl = input.closest('.filter-bar')
        ? input.closest('.filter-bar').querySelector('.filter-count')
        : null;

      input.addEventListener('input', function () {
        var query = input.value.toLowerCase().trim();
        var rows = table.querySelectorAll('tbody tr');
        var visible = 0;

        rows.forEach(function (row) {
          var text = row.textContent.toLowerCase();
          var match = query === '' || text.indexOf(query) !== -1;
          row.style.display = match ? '' : 'none';
          if (match) visible++;
        });

        if (countEl) {
          countEl.textContent = query ? visible + ' / ' + rows.length + ' 条' : '';
        }
      });
    });
  }

  /* =========================================================================
     6. STICKY KPI SHADOW (~10 lines)
     ========================================================================= */

  function initStickyKpiShadow() {
    var kpiBar = document.querySelector('.kpi-bar');
    if (!kpiBar) return;

    function onScroll() {
      kpiBar.classList.toggle('scrolled', window.scrollY > 10);
    }

    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll(); // run once on load in case page is already scrolled
  }

  /* =========================================================================
     7. PRINT BUTTON (~10 lines)
     ========================================================================= */

  function initPrint() {
    var btn = document.getElementById('btn-print');
    if (!btn) return;
    btn.addEventListener('click', function () {
      window.print();
    });
  }

  /* =========================================================================
     8. CHART INITIALIZATION (~60 lines)
     ========================================================================= */

  function initCharts() {
    // Chart.js may be loaded async; skip gracefully if not available
    if (typeof Chart === 'undefined') {
      console.warn('[Report V3] Chart.js not loaded — skipping chart init.');
      return;
    }

    var canvases = document.querySelectorAll('canvas[data-chart-config]');

    canvases.forEach(function (canvas) {
      var raw = canvas.getAttribute('data-chart-config');
      if (!raw) return;

      var config;
      try {
        config = JSON.parse(raw);
      } catch (e) {
        console.error('[Report V3] Invalid chart config JSON on', canvas.id || canvas, e);
        return;
      }

      // Apply sensible defaults for screen rendering
      if (!config.options) config.options = {};
      if (!config.options.responsive) config.options.responsive = true;
      if (config.options.maintainAspectRatio === undefined) {
        config.options.maintainAspectRatio = true;
      }

      // Ensure legend and tooltip defaults are set
      if (!config.options.plugins) config.options.plugins = {};
      if (!config.options.plugins.legend) {
        config.options.plugins.legend = { position: 'bottom' };
      }
      if (!config.options.plugins.tooltip) {
        config.options.plugins.tooltip = { mode: 'index', intersect: false };
      }

      try {
        new Chart(canvas, config);
      } catch (e) {
        console.error('[Report V3] Chart creation failed for', canvas.id || canvas, e);
      }
    });
  }

  /* =========================================================================
     BOOT — run all inits after DOM ready
     ========================================================================= */

  function boot() {
    initTabs();
    initCollapsible();
    initLightbox();
    initTableSort();
    initTableFilter();
    initStickyKpiShadow();
    initPrint();
    initCharts();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

}());
