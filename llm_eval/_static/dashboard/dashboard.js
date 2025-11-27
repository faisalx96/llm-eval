(() => {
  const state = {
    runs: null,
    searchQuery: '',
    sortKey: 'date-desc',
  };

  const el = (id) => document.getElementById(id);

  // Heartbeat to keep server alive
  function startHeartbeat() {
    setInterval(() => {
      fetch('/api/heartbeat', { method: 'POST' }).catch(() => {});
    }, 30000);
  }

  // Fetch runs from API
  async function fetchRuns() {
    try {
      const response = await fetch('/api/runs');
      const data = await response.json();
      state.runs = data;
      el('last-updated').textContent = `Last updated: ${new Date().toLocaleTimeString()}`;
      render();
    } catch (err) {
      console.error('Failed to fetch runs:', err);
      el('loading').textContent = 'Failed to load runs. Is the server running?';
    }
  }

  // Format date
  function formatDate(isoStr) {
    try {
      const d = new Date(isoStr);
      return d.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoStr || '--';
    }
  }

  // Format success rate
  function formatSuccessRate(rate) {
    const pct = (rate * 100).toFixed(1);
    return `${pct}%`;
  }

  // Get success rate color class
  function getSuccessClass(rate) {
    if (rate >= 0.9) return 'success';
    if (rate >= 0.7) return 'warning';
    return 'error';
  }

  // Flatten runs for filtering/sorting
  function flattenRuns(data) {
    const runs = [];
    if (!data || !data.tasks) return runs;
    for (const [taskName, models] of Object.entries(data.tasks)) {
      for (const [modelName, runList] of Object.entries(models)) {
        for (const run of runList) {
          runs.push({ ...run, task_name: taskName, model_name: modelName });
        }
      }
    }
    return runs;
  }

  // Filter and sort runs
  function getFilteredRuns() {
    let runs = flattenRuns(state.runs);

    // Filter by search
    if (state.searchQuery) {
      const q = state.searchQuery.toLowerCase();
      runs = runs.filter(
        (r) =>
          r.run_id.toLowerCase().includes(q) ||
          r.task_name.toLowerCase().includes(q) ||
          r.model_name.toLowerCase().includes(q) ||
          r.dataset_name.toLowerCase().includes(q)
      );
    }

    // Sort
    switch (state.sortKey) {
      case 'date-desc':
        runs.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
        break;
      case 'date-asc':
        runs.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp));
        break;
      case 'task-asc':
        runs.sort((a, b) => a.task_name.localeCompare(b.task_name));
        break;
      case 'success-desc':
        runs.sort((a, b) => b.success_rate - a.success_rate);
        break;
    }

    return runs;
  }

  // Group runs by task, then by model
  function groupRuns(runs) {
    const groups = {};
    for (const run of runs) {
      if (!groups[run.task_name]) groups[run.task_name] = {};
      if (!groups[run.task_name][run.model_name]) groups[run.task_name][run.model_name] = [];
      groups[run.task_name][run.model_name].push(run);
    }
    return groups;
  }

  // Render run card
  function renderRunCard(run) {
    const successClass = getSuccessClass(run.success_rate);
    const metricsHtml = (run.metrics || [])
      .map((m) => `<span class="metric-badge">${m}</span>`)
      .join('');

    return `
      <div class="run-card" data-file="${encodeURIComponent(run.file_path)}">
        <div class="run-header">
          <span class="run-name">${run.run_id}</span>
          <span class="run-date">${formatDate(run.timestamp)}</span>
        </div>
        <div class="run-stats">
          <div class="stat">
            <span class="label">Dataset</span>
            <span class="value">${run.dataset_name || '--'}</span>
          </div>
          <div class="stat">
            <span class="label">Items</span>
            <span class="value">${run.total_items || 0}</span>
          </div>
          <div class="stat">
            <span class="label">Success</span>
            <span class="value ${successClass}">${formatSuccessRate(run.success_rate)}</span>
          </div>
        </div>
        <div class="metrics">${metricsHtml}</div>
      </div>
    `;
  }

  // Render all runs
  function render() {
    const loading = el('loading');
    const empty = el('empty');
    const container = el('runs-container');

    if (!state.runs) {
      loading.style.display = 'block';
      empty.style.display = 'none';
      container.innerHTML = '';
      return;
    }

    loading.style.display = 'none';

    const runs = getFilteredRuns();

    if (runs.length === 0) {
      empty.style.display = 'block';
      container.innerHTML = '';
      return;
    }

    empty.style.display = 'none';

    const grouped = groupRuns(runs);
    const taskNames = Object.keys(grouped).sort();

    let html = '';

    for (const taskName of taskNames) {
      const models = grouped[taskName];
      const modelNames = Object.keys(models).sort();
      const totalRuns = modelNames.reduce((sum, m) => sum + models[m].length, 0);

      html += `
        <div class="task-group">
          <div class="task-header">
            <span class="arrow">▼</span>
            <span class="task-name">${taskName}</span>
            <span class="task-count">${totalRuns} run${totalRuns !== 1 ? 's' : ''}</span>
          </div>
          <div class="task-content">
      `;

      for (const modelName of modelNames) {
        const modelRuns = models[modelName];

        html += `
          <div class="model-group">
            <div class="model-header">
              <span class="arrow">▼</span>
              <span class="model-name">${modelName}</span>
              <span class="model-count">${modelRuns.length}</span>
            </div>
            <div class="model-content">
              <div class="run-cards">
                ${modelRuns.map(renderRunCard).join('')}
              </div>
            </div>
          </div>
        `;
      }

      html += `
          </div>
        </div>
      `;
    }

    container.innerHTML = html;

    // Wire up accordion toggles
    container.querySelectorAll('.task-header').forEach((header) => {
      header.addEventListener('click', () => {
        header.parentElement.classList.toggle('collapsed');
      });
    });

    container.querySelectorAll('.model-header').forEach((header) => {
      header.addEventListener('click', () => {
        header.parentElement.classList.toggle('collapsed');
      });
    });

    // Wire up run card clicks
    container.querySelectorAll('.run-card').forEach((card) => {
      card.addEventListener('click', () => {
        const filePath = decodeURIComponent(card.dataset.file);
        // Store file path for the detail page
        sessionStorage.setItem('dashboardRunFile', filePath);
        // Navigate to run detail view
        window.location.href = `/run/${encodeURIComponent(filePath)}`;
      });
    });
  }

  // Event listeners
  el('search').addEventListener('input', (e) => {
    state.searchQuery = e.target.value;
    render();
  });

  el('sort').addEventListener('change', (e) => {
    state.sortKey = e.target.value;
    render();
  });

  // Initialize
  startHeartbeat();
  fetchRuns();

  // Refresh runs every 60 seconds
  setInterval(fetchRuns, 60000);
})();
