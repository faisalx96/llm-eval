# LLM-Eval Design System

A comprehensive, developer-focused UI component library built with React, TypeScript, and Tailwind CSS for the LLM-Eval platform.

## Overview

This design system provides a cohesive set of components optimized for technical interfaces, data-dense displays, and developer workflows. It emphasizes accessibility, performance, and developer experience while maintaining visual consistency across the platform.

## Getting Started

### Installation

```bash
# Install dependencies
npm install clsx class-variance-authority

# Components are already included in the project
```

### Usage

```tsx
import { Button, Card, Table } from '@/components';

function MyComponent() {
  return (
    <Card>
      <Card.Header>
        <Card.Title>Evaluation Results</Card.Title>
      </Card.Header>
      <Card.Content>
        <Button variant="primary">Run Evaluation</Button>
      </Card.Content>
    </Card>
  );
}
```

## Design Tokens

### Color System

The design system uses a developer-focused color palette:

- **Neutrals**: Grays for technical interfaces (50-950 scale)
- **Primary**: Professional blue for CTAs and highlights
- **Success**: Green for positive states and metrics
- **Warning**: Amber for caution and intermediate states
- **Danger**: Red for errors and critical states
- **Info**: Cyan for informational states

### Typography

- **Font Family**: Inter for UI, Fira Code for code
- **Scale**: 12px to 60px with consistent line heights
- **Weights**: 100-900 with semantic naming

### Spacing

8px base grid system with consistent spacing scale from 2px to 384px.

## Components

### Core UI Components

#### Button
Multiple variants for different use cases:
```tsx
<Button variant="default" size="md">Primary Action</Button>
<Button variant="secondary">Secondary Action</Button>
<Button variant="ghost">Subtle Action</Button>
<Button loading>Processing...</Button>
```

**Variants**: `default` | `secondary` | `ghost` | `outline` | `success` | `warning` | `danger` | `link`
**Sizes**: `sm` | `md` | `lg` | `icon`

#### Card
Flexible container for content grouping:
```tsx
<Card variant="elevated" padding="lg">
  <CardHeader>
    <CardTitle>Evaluation Summary</CardTitle>
    <CardDescription>Latest results</CardDescription>
  </CardHeader>
  <CardContent>
    {/* Content here */}
  </CardContent>
  <CardFooter>
    <Button>View Details</Button>
  </CardFooter>
</Card>
```

#### Table
Data-dense display optimized for evaluation results:
```tsx
<Table>
  <TableHeader>
    <TableRow>
      <TableHead sortable sorted="desc">Test Case</TableHead>
      <TableHead numeric>Score</TableHead>
    </TableRow>
  </TableHeader>
  <TableBody>
    <TableRow>
      <TableCell>Context relevance</TableCell>
      <TableCell numeric>0.92</TableCell>
    </TableRow>
  </TableBody>
</Table>
```

#### Badge
Status indicators and labels:
```tsx
<Badge variant="success">Passed</Badge>
<Badge variant="warning">Warning</Badge>
<Badge variant="danger">Failed</Badge>
```

#### Form Controls
Comprehensive form components with validation:
```tsx
<Input
  label="Email"
  type="email"
  placeholder="Enter email"
  error="Invalid email format"
  leftIcon={<EmailIcon />}
/>

<Select
  label="Model"
  options={[
    { value: 'gpt-4', label: 'GPT-4' },
    { value: 'claude-3', label: 'Claude 3' }
  ]}
/>

<Textarea
  label="Prompt"
  maxLength={500}
  showCharCount
/>
```

#### Modal
Overlay dialogs with focus management:
```tsx
<Modal isOpen={isOpen} onClose={onClose} title="Settings">
  <ModalBody>
    {/* Modal content */}
  </ModalBody>
  <ModalFooter>
    <Button variant="outline" onClick={onClose}>Cancel</Button>
    <Button onClick={onSave}>Save</Button>
  </ModalFooter>
</Modal>
```

#### Tabs
Navigation between related content:
```tsx
<Tabs
  items={[
    { id: 'results', label: 'Results', content: <ResultsView /> },
    { id: 'metrics', label: 'Metrics', content: <MetricsView /> }
  ]}
  variant="underline"
/>
```

### Loading States

#### Spinner
Loading indicators in multiple sizes:
```tsx
<Spinner size="md" />
<LoadingOverlay loading={isLoading}>
  <ContentComponent />
</LoadingOverlay>
```

#### Skeleton
Placeholder content during loading:
```tsx
<Skeleton variant="text" lines={3} />
<Skeleton variant="rectangular" width={300} height={200} />
<TableSkeleton rows={5} columns={4} />
<CardSkeleton showHeader bodyLines={4} />
```

### Layout Components

#### Container
Responsive content wrapper:
```tsx
<Container size="lg" padding="md">
  {/* Page content */}
</Container>
```

#### Grid System
Flexible grid layouts:
```tsx
<Grid cols={3} gap="md" responsive={{ sm: 1, md: 2, lg: 3 }}>
  <GridItem colSpan={2}>Main content</GridItem>
  <GridItem>Sidebar</GridItem>
</Grid>
```

#### Flex Layout
Flexbox utility component:
```tsx
<Flex direction="row" justify="between" align="center" gap="md">
  <div>Left content</div>
  <div>Right content</div>
</Flex>
```

#### Sidebar Navigation
Application navigation with collapsible state:
```tsx
<SidebarLayout
  sidebar={
    <Sidebar
      items={navigationItems}
      collapsed={isCollapsed}
      onToggleCollapse={toggleSidebar}
    />
  }
>
  <MainContent />
</SidebarLayout>
```

## Accessibility

All components follow WAI-ARIA guidelines:

- **Keyboard Navigation**: Full keyboard support
- **Screen Readers**: Proper ARIA labels and roles
- **Focus Management**: Visible focus indicators and logical tab order
- **Color Contrast**: WCAG AA compliant contrast ratios
- **Motion**: Respects `prefers-reduced-motion`

## Dark Mode

Built-in dark mode support using CSS custom properties:

```css
/* Automatic dark mode based on system preference */
@media (prefers-color-scheme: dark) {
  /* Dark mode styles */
}
```

## Performance

- **Tree Shaking**: Import only what you need
- **Bundle Optimization**: Minimal runtime overhead
- **Async Loading**: Support for code splitting
- **Memory Efficient**: Proper cleanup and refs

## Browser Support

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## Development

### Component Demo

Visit `/components` to see all components in action with interactive examples.

### Adding New Components

1. Create component in `components/ui/` or `components/layout/`
2. Follow established patterns for props and styling
3. Add TypeScript interfaces
4. Include accessibility features
5. Update exports in `components/index.ts`
6. Add to demo page

### Design Token Updates

Update tokens in `lib/design-tokens.ts` and corresponding CSS custom properties in `app/globals.css`.

## File Structure

```
frontend/
├── components/
│   ├── ui/                 # Core UI components
│   │   ├── button.tsx
│   │   ├── card.tsx
│   │   ├── table.tsx
│   │   └── ...
│   ├── layout/             # Layout components
│   │   ├── container.tsx
│   │   ├── grid.tsx
│   │   └── sidebar.tsx
│   └── index.ts            # Component exports
├── lib/
│   ├── design-tokens.ts    # Design system tokens
│   └── utils.ts            # Utility functions
├── app/
│   ├── globals.css         # Global styles and CSS variables
│   └── components/
│       └── page.tsx        # Component showcase
└── DESIGN_SYSTEM.md        # This documentation
```

## Contributing

1. Follow TypeScript best practices
2. Maintain accessibility standards
3. Add proper documentation
4. Include component in demo page
5. Test across supported browsers

## Migration from Other Systems

### From Material-UI
- Replace `Box` with `Flex` or `Grid`
- Replace `Typography` with semantic HTML + Tailwind classes
- Replace `Paper` with `Card`

### From Chakra UI
- Replace `Stack` with `Flex` or `Grid`
- Replace `useColorMode` with CSS custom properties
- Replace `Box` with layout components

## Resources

- [Tailwind CSS Documentation](https://tailwindcss.com/docs)
- [React Accessibility Guide](https://react.dev/learn/accessibility)
- [WAI-ARIA Authoring Practices](https://www.w3.org/WAI/ARIA/apg/)
- [Class Variance Authority](https://cva.style/docs)

---

**Version**: 1.0.0  
**Last Updated**: 2025-08-02  
**Maintainer**: LLM-Eval Frontend Team
