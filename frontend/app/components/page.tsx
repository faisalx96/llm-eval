'use client';

import React from 'react';
import {
  Button,
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardFooter,
  Badge,
  Input,
  Select,
  Textarea,
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
  TableEmpty,
  Tabs,
  Modal,
  ModalHeader,
  ModalBody,
  ModalFooter,
  Spinner,
  LoadingOverlay,
  Skeleton,
  SkeletonBox,
  TableSkeleton,
  CardSkeleton,
  Container,
  Grid,
  GridItem,
  Flex,
  Sidebar,
  SidebarLayout,
} from '@/components';

const ComponentShowcase: React.FC = () => {
  const [modalOpen, setModalOpen] = React.useState(false);
  const [loadingDemo, setLoadingDemo] = React.useState(false);
  const [selectedTab, setSelectedTab] = React.useState('buttons');

  const sidebarItems = [
    {
      id: 'overview',
      label: 'Overview',
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
        </svg>
      ),
      active: true,
    },
    {
      id: 'components',
      label: 'Components',
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
        </svg>
      ),
      children: [
        { id: 'buttons', label: 'Buttons', onClick: () => setSelectedTab('buttons') },
        { id: 'forms', label: 'Form Controls', onClick: () => setSelectedTab('forms') },
        { id: 'data', label: 'Data Display', onClick: () => setSelectedTab('data') },
        { id: 'layout', label: 'Layout', onClick: () => setSelectedTab('layout') },
      ],
    },
    {
      id: 'settings',
      label: 'Settings',
      icon: (
        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
      ),
    },
  ];

  const tabItems = [
    {
      id: 'buttons',
      label: 'Buttons',
      content: (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Button Variants</CardTitle>
              <CardDescription>Different button styles and states</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-4">
                <Flex gap="md" wrap="wrap">
                  <Button variant="default">Primary</Button>
                  <Button variant="secondary">Secondary</Button>
                  <Button variant="ghost">Ghost</Button>
                  <Button variant="outline">Outline</Button>
                  <Button variant="success">Success</Button>
                  <Button variant="warning">Warning</Button>
                  <Button variant="danger">Danger</Button>
                  <Button variant="link">Link</Button>
                </Flex>
                
                <Flex gap="md" wrap="wrap">
                  <Button size="sm">Small</Button>
                  <Button size="md">Medium</Button>
                  <Button size="lg">Large</Button>
                  <Button size="icon">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6v6m0 0v6m0-6h6m-6 0H6" />
                    </svg>
                  </Button>
                </Flex>

                <Flex gap="md" wrap="wrap">
                  <Button loading>Loading</Button>
                  <Button disabled>Disabled</Button>
                  <Button 
                    leftIcon={
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                      </svg>
                    }
                  >
                    With Icon
                  </Button>
                </Flex>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Badges</CardTitle>
              <CardDescription>Status indicators and labels</CardDescription>
            </CardHeader>
            <CardContent>
              <Flex gap="md" wrap="wrap">
                <Badge variant="default">Default</Badge>
                <Badge variant="secondary">Secondary</Badge>
                <Badge variant="outline">Outline</Badge>
                <Badge variant="success">Success</Badge>
                <Badge variant="warning">Warning</Badge>
                <Badge variant="danger">Danger</Badge>
                <Badge variant="info">Info</Badge>
              </Flex>
            </CardContent>
          </Card>
        </div>
      ),
    },
    {
      id: 'forms',
      label: 'Form Controls',
      content: (
        <div className="space-y-6 max-w-2xl">
          <Card>
            <CardHeader>
              <CardTitle>Input Components</CardTitle>
              <CardDescription>Text inputs, selects, and textareas</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <Input
                label="Email"
                type="email"
                placeholder="Enter your email"
                hint="We'll never share your email with anyone else."
              />
              
              <Input
                label="Password"
                type="password"
                placeholder="Enter your password"
                error="Password must be at least 8 characters"
              />

              <Select
                label="Country"
                placeholder="Select a country"
                options={[
                  { value: 'us', label: 'United States' },
                  { value: 'ca', label: 'Canada' },
                  { value: 'uk', label: 'United Kingdom' },
                  { value: 'au', label: 'Australia' },
                ]}
                hint="Choose your country of residence"
              />

              <Textarea
                label="Description"
                placeholder="Enter a description"
                rows={4}
                maxLength={500}
                showCharCount={true}
                hint="Provide a detailed description"
              />
            </CardContent>
          </Card>
        </div>
      ),
    },
    {
      id: 'data',
      label: 'Data Display',
      content: (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Data Table</CardTitle>
              <CardDescription>Evaluation results and metrics</CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead sortable sorted="desc">Test Case</TableHead>
                    <TableHead sortable>Score</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Duration</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow>
                    <TableCell>Text summarization accuracy</TableCell>
                    <TableCell>0.92</TableCell>
                    <TableCell>
                      <Badge variant="success">Passed</Badge>
                    </TableCell>
                    <TableCell numeric>1.2s</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>Response relevance</TableCell>
                    <TableCell>0.88</TableCell>
                    <TableCell>
                      <Badge variant="success">Passed</Badge>
                    </TableCell>
                    <TableCell numeric>0.8s</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>Hallucination detection</TableCell>
                    <TableCell>0.65</TableCell>
                    <TableCell>
                      <Badge variant="warning">Warning</Badge>
                    </TableCell>
                    <TableCell numeric>2.1s</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>Context faithfulness</TableCell>
                    <TableCell>0.45</TableCell>
                    <TableCell>
                      <Badge variant="danger">Failed</Badge>
                    </TableCell>
                    <TableCell numeric>1.5s</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Loading States</CardTitle>
              <CardDescription>Skeleton loaders and spinners</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center gap-4">
                <Spinner size="sm" />
                <Spinner size="md" />
                <Spinner size="lg" />
                <Spinner size="xl" />
              </div>

              <LoadingOverlay loading={loadingDemo}>
                <div className="h-32 bg-neutral-100 dark:bg-neutral-800 rounded-md flex items-center justify-center">
                  <Button onClick={() => setLoadingDemo(!loadingDemo)}>
                    Toggle Loading
                  </Button>
                </div>
              </LoadingOverlay>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <SkeletonBox className="h-24" />
                <div className="space-y-2">
                  <SkeletonBox className="h-4" />
                  <SkeletonBox className="h-4" />
                  <SkeletonBox className="h-4 w-3/4" />
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      ),
    },
    {
      id: 'layout',
      label: 'Layout',
      content: (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Grid System</CardTitle>
              <CardDescription>Responsive grid layouts</CardDescription>
            </CardHeader>
            <CardContent>
              <Grid cols={3} gap="md" responsive={{ sm: 1, md: 2, lg: 3 }}>
                <GridItem>
                  <div className="h-20 bg-primary-100 dark:bg-primary-900 rounded-md flex items-center justify-center">
                    1
                  </div>
                </GridItem>
                <GridItem>
                  <div className="h-20 bg-primary-100 dark:bg-primary-900 rounded-md flex items-center justify-center">
                    2
                  </div>
                </GridItem>
                <GridItem>
                  <div className="h-20 bg-primary-100 dark:bg-primary-900 rounded-md flex items-center justify-center">
                    3
                  </div>
                </GridItem>
              </Grid>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Flex Layout</CardTitle>
              <CardDescription>Flexible box layouts</CardDescription>
            </CardHeader>
            <CardContent>
              <Flex direction="row" justify="between" align="center" className="h-20 bg-neutral-50 dark:bg-neutral-800 rounded-md px-4">
                <div className="w-16 h-8 bg-primary-500 rounded"></div>
                <div className="w-16 h-8 bg-success-500 rounded"></div>
                <div className="w-16 h-8 bg-warning-500 rounded"></div>
              </Flex>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Modal Dialog</CardTitle>
              <CardDescription>Overlays and dialogs</CardDescription>
            </CardHeader>
            <CardContent>
              <Button onClick={() => setModalOpen(true)}>
                Open Modal
              </Button>
            </CardContent>
          </Card>
        </div>
      ),
    },
  ];

  return (
    <div className="h-screen bg-neutral-50 dark:bg-neutral-900">
      <SidebarLayout
        sidebar={
          <Sidebar
            items={sidebarItems}
            header={
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 bg-primary-500 rounded-md flex items-center justify-center">
                  <span className="text-white font-bold text-sm">LE</span>
                </div>
                <span className="font-semibold text-neutral-900 dark:text-neutral-100">
                  LLM-Eval
                </span>
              </div>
            }
            footer={
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 bg-neutral-200 dark:bg-neutral-700 rounded-full"></div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100 truncate">
                    Developer
                  </p>
                  <p className="text-xs text-neutral-500 dark:text-neutral-400 truncate">
                    demo@example.com
                  </p>
                </div>
              </div>
            }
          />
        }
      >
        <Container size="full" className="h-full overflow-auto">
          <div className="py-8">
            <div className="mb-8">
              <h1 className="text-3xl font-bold text-neutral-900 dark:text-neutral-100 mb-2">
                Design System Components
              </h1>
              <p className="text-neutral-600 dark:text-neutral-400">
                A comprehensive component library for the LLM-Eval platform
              </p>
            </div>

            <Tabs
              items={tabItems}
              activeTab={selectedTab}
              onTabChange={setSelectedTab}
              variant="underline"
            />
          </div>
        </Container>
      </SidebarLayout>

      {/* Modal Demo */}
      <Modal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
        title="Evaluation Settings"
        size="lg"
      >
        <ModalHeader>
          <h3 className="text-lg font-semibold">Configure Evaluation</h3>
          <p className="text-sm text-neutral-600 dark:text-neutral-400">
            Set up your evaluation parameters
          </p>
        </ModalHeader>
        
        <ModalBody>
          <div className="space-y-4">
            <Select
              label="Evaluation Model"
              placeholder="Select a model"
              options={[
                { value: 'gpt-4', label: 'GPT-4' },
                { value: 'gpt-3.5', label: 'GPT-3.5 Turbo' },
                { value: 'claude-3', label: 'Claude 3 Opus' },
              ]}
            />
            <Input
              label="Temperature"
              type="number"
              placeholder="0.7"
              min="0"
              max="2"
              step="0.1"
            />
            <Textarea
              label="System Prompt"
              placeholder="Enter system prompt..."
              rows={4}
            />
          </div>
        </ModalBody>
        
        <ModalFooter>
          <Button variant="outline" onClick={() => setModalOpen(false)}>
            Cancel
          </Button>
          <Button onClick={() => setModalOpen(false)}>
            Save Settings
          </Button>
        </ModalFooter>
      </Modal>
    </div>
  );
};

export default ComponentShowcase;