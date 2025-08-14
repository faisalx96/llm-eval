import '@testing-library/jest-dom'

// Mock Next.js router
jest.mock('next/navigation', () => ({
  useRouter() {
    return {
      push: jest.fn(),
      replace: jest.fn(),
      prefetch: jest.fn(),
      back: jest.fn(),
      forward: jest.fn(),
      refresh: jest.fn(),
    }
  },
  useSearchParams() {
    return new URLSearchParams()
  },
  usePathname() {
    return ''
  }
}))

// Mock API client
jest.mock('@/lib/api', () => ({
  apiClient: {
    getRuns: jest.fn(),
    getRunById: jest.fn(),
    getRunDetails: jest.fn(),
    compareRuns: jest.fn(),
    exportComparison: jest.fn(),
    getConfigurations: jest.fn(),
    createConfiguration: jest.fn(),
    updateConfiguration: jest.fn(),
    getMetrics: jest.fn(),
    validateMetric: jest.fn(),
    getTemplates: jest.fn(),
    recommendTemplates: jest.fn(),
    getDatasets: jest.fn(),
    getDatasetPreview: jest.fn(),
    getTasks: jest.fn(),
    executeTask: jest.fn(),
    getTaskStatus: jest.fn(),
    pauseTask: jest.fn(),
    resumeTask: jest.fn(),
    cancelTask: jest.fn(),
  }
}))

// Mock WebSocket
global.WebSocket = jest.fn(() => ({
  addEventListener: jest.fn(),
  removeEventListener: jest.fn(),
  send: jest.fn(),
  close: jest.fn(),
  readyState: 1,
}))

// Mock ResizeObserver
global.ResizeObserver = jest.fn().mockImplementation(() => ({
  observe: jest.fn(),
  unobserve: jest.fn(),
  disconnect: jest.fn(),
}))

// Mock IntersectionObserver
global.IntersectionObserver = jest.fn().mockImplementation(() => ({
  observe: jest.fn(),
  unobserve: jest.fn(),
  disconnect: jest.fn(),
}))

// Mock URL.createObjectURL
Object.defineProperty(global.URL, 'createObjectURL', {
  writable: true,
  value: jest.fn(() => 'blob:mock-url'),
})

Object.defineProperty(global.URL, 'revokeObjectURL', {
  writable: true,
  value: jest.fn(),
})

// Mock window.history
Object.defineProperty(window, 'history', {
  writable: true,
  value: {
    replaceState: jest.fn(),
    pushState: jest.fn(),
    back: jest.fn(),
    forward: jest.fn(),
  },
})

// Mock console methods to reduce noise in tests
global.console = {
  ...console,
  warn: jest.fn(),
  error: jest.fn(),
}

// Mock custom hooks - make them jest mock functions
jest.mock('@/hooks/useMetrics', () => ({
  useMetrics: jest.fn(() => ({
    metrics: [],
    metricsByCategory: {},
    loading: false,
    error: null,
    refetch: jest.fn(),
  })),
  useMetricSelector: jest.fn(() => ({
    selectedMetrics: [],
    addMetric: jest.fn(),
    removeMetric: jest.fn(),
    updateMetricParameters: jest.fn(),
    clearMetrics: jest.fn(),
    validateMetric: jest.fn(),
    isMetricSelected: jest.fn(() => false),
    getMetricSelection: jest.fn(() => null),
  })),
}))

jest.mock('@/hooks/useDatasets', () => ({
  useDatasets: jest.fn(() => ({
    datasets: [],
    loading: false,
    error: null,
    refetch: jest.fn(),
  })),
  useDatasetItems: jest.fn(() => ({
    items: [],
    loading: false,
    error: null,
    hasMore: false,
    loadMore: jest.fn(),
  })),
}))

jest.mock('@/hooks/useTemplates', () => ({
  useTemplates: jest.fn(() => ({
    templates: [],
    loading: false,
    error: null,
    refetch: jest.fn(),
  })),
  useTemplateRecommendations: jest.fn(() => ({
    recommendations: [],
    loading: false,
    error: null,
    getRecommendations: jest.fn(),
  })),
}))

jest.mock('@/hooks/useTaskConfiguration', () => ({
  useTaskConfiguration: jest.fn(() => ({
    configuration: {},
    updateConfiguration: jest.fn(),
    validateConfiguration: jest.fn(),
    testConfiguration: jest.fn(),
    saveConfiguration: jest.fn(),
    loading: false,
    error: null,
  })),
  useConfigurationWizard: jest.fn(() => ({
    wizardState: {
      currentStep: 0,
      steps: [],
      configuration: {},
      validation: {},
      canNavigateForward: true,
      canNavigateBack: false,
    },
    updateConfiguration: jest.fn(),
    validateCurrentStep: jest.fn(() => true),
    nextStep: jest.fn(),
    previousStep: jest.fn(),
    goToStep: jest.fn(),
    submitConfiguration: jest.fn(),
    autoTestConfiguration: jest.fn(),
    loading: false,
    error: null,
  })),
}))

jest.mock('@/hooks/useRuns', () => ({
  useRuns: jest.fn(() => ({
    runs: [],
    loading: false,
    error: null,
    pagination: { page: 1, pageSize: 20, totalCount: 0 },
    filters: {},
    setFilters: jest.fn(),
    setPage: jest.fn(),
    refetch: jest.fn(),
  })),
}))

jest.mock('@/hooks/useRunDetail', () => ({
  useRunDetail: jest.fn(() => ({
    run: null,
    metrics: null,
    items: [],
    loading: false,
    error: null,
    refetch: jest.fn(),
  })),
}))

jest.mock('@/hooks/useRunComparison', () => ({
  useRunComparison: jest.fn(() => ({
    comparison: null,
    loading: false,
    error: null,
    compareRuns: jest.fn(),
    exportComparison: jest.fn(),
  })),
}))

jest.mock('@/hooks/useWebSocket', () => ({
  useWebSocket: jest.fn(() => ({
    isConnected: false,
    lastMessage: null,
    sendMessage: jest.fn(),
    subscribe: jest.fn(),
    unsubscribe: jest.fn(),
  })),
}))

// Mock the main hooks barrel export
jest.mock('@/hooks', () => ({
  useRuns: jest.fn(() => ({
    runs: [],
    loading: false,
    error: null,
    pagination: { page: 1, pageSize: 20, totalCount: 0 },
    filters: {},
    setFilters: jest.fn(),
    setPage: jest.fn(),
    refetch: jest.fn(),
  })),
  useWebSocket: jest.fn(() => ({
    isConnected: false,
    lastMessage: null,
    sendMessage: jest.fn(),
    subscribe: jest.fn(),
    unsubscribe: jest.fn(),
  })),
  useRunDetail: jest.fn(() => ({
    run: null,
    metrics: null,
    items: [],
    loading: false,
    error: null,
    refetch: jest.fn(),
  })),
  useRunComparison: jest.fn(() => ({
    comparison: null,
    loading: false,
    error: null,
    compareRuns: jest.fn(),
    exportComparison: jest.fn(),
  })),
  useDatasets: jest.fn(() => ({
    datasets: [],
    loading: false,
    error: null,
    refetch: jest.fn(),
  })),
  useDataset: jest.fn(() => ({
    dataset: null,
    loading: false,
    error: null,
    refetch: jest.fn(),
  })),
  useDatasetItems: jest.fn(() => ({
    items: [],
    loading: false,
    error: null,
    hasMore: false,
    loadMore: jest.fn(),
  })),
  useMetrics: jest.fn(() => ({
    metrics: [],
    metricsByCategory: {},
    loading: false,
    error: null,
    refetch: jest.fn(),
  })),
  useMetric: jest.fn(() => ({
    metric: null,
    loading: false,
    error: null,
    refetch: jest.fn(),
  })),
  useMetricCompatibility: jest.fn(() => ({
    compatibility: {
      compatible: true,
      issues: [],
    },
    loading: false,
    error: null,
  })),
  useMetricSelector: jest.fn(() => ({
    selectedMetrics: [],
    addMetric: jest.fn(),
    removeMetric: jest.fn(),
    updateMetricParameters: jest.fn(),
    clearMetrics: jest.fn(),
    validateMetric: jest.fn(),
    isMetricSelected: jest.fn(() => false),
    getMetricSelection: jest.fn(() => null),
  })),
  useTaskConfigurations: jest.fn(() => ({
    configurations: [],
    loading: false,
    error: null,
    refetch: jest.fn(),
  })),
  useTaskConfiguration: jest.fn(() => ({
    configuration: {},
    updateConfiguration: jest.fn(),
    validateConfiguration: jest.fn(),
    testConfiguration: jest.fn(),
    saveConfiguration: jest.fn(),
    loading: false,
    error: null,
  })),
  useConfigurationWizard: jest.fn(() => ({
    wizardState: {
      currentStep: 0,
      steps: [],
      configuration: {},
      validation: {},
      canNavigateForward: true,
      canNavigateBack: false,
    },
    updateConfiguration: jest.fn(),
    validateCurrentStep: jest.fn(() => true),
    nextStep: jest.fn(),
    previousStep: jest.fn(),
    goToStep: jest.fn(),
    submitConfiguration: jest.fn(),
    autoTestConfiguration: jest.fn(),
    loading: false,
    error: null,
  })),
  useTemplates: jest.fn(() => ({
    templates: [],
    loading: false,
    error: null,
    refetch: jest.fn(),
  })),
  useTemplate: jest.fn(() => ({
    template: null,
    loading: false,
    error: null,
    refetch: jest.fn(),
  })),
  useTemplateRecommendations: jest.fn(() => ({
    recommendations: [],
    loading: false,
    error: null,
    getRecommendations: jest.fn(),
  })),
}))

