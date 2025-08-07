# LLM-Eval Frontend

A modern Next.js application for the LLM-Eval platform - a UI-first LLM evaluation tool designed for developers.

## Tech Stack

- **Framework**: Next.js 15+ with App Router
- **Language**: TypeScript for type safety
- **Styling**: Tailwind CSS for responsive design
- **Code Quality**: ESLint + Prettier for consistent formatting
- **Package Manager**: npm

## Getting Started

### Prerequisites

- Node.js 18+ and npm
- Access to the LLM-Eval Python backend

### Installation

1. **Install dependencies**:

   ```bash
   npm install
   ```

2. **Start development server**:

   ```bash
   npm run dev
   ```

3. **Open your browser**:
   Navigate to [http://localhost:3000](http://localhost:3000)

## Available Scripts

| Script                 | Description                             |
| ---------------------- | --------------------------------------- |
| `npm run dev`          | Start development server with Turbopack |
| `npm run build`        | Build production application            |
| `npm run start`        | Start production server                 |
| `npm run lint`         | Run ESLint checks                       |
| `npm run lint:fix`     | Auto-fix ESLint issues                  |
| `npm run format`       | Format code with Prettier               |
| `npm run format:check` | Check code formatting                   |
| `npm run type-check`   | Type check without building             |
| `npm run clean`        | Clean build artifacts                   |
| `npm run analyze`      | Analyze bundle size                     |

## Project Structure

```
frontend/
├── app/                    # Next.js App Router pages
│   ├── globals.css        # Global styles
│   ├── layout.tsx         # Root layout
│   └── page.tsx           # Home page
├── components/            # Reusable React components
├── hooks/                 # Custom React hooks
├── lib/                   # Utilities and configurations
├── types/                 # TypeScript type definitions
├── utils/                 # Helper functions
└── public/               # Static assets
```

## Development Guidelines

### Code Style

- **TypeScript**: Use strict typing, avoid `any` when possible
- **Components**: Functional components with TypeScript interfaces
- **Naming**: PascalCase for components, camelCase for functions/variables
- **Imports**: Use absolute imports with `@/` prefix for internal modules

### Component Structure

```typescript
// components/ui/Button.tsx
interface ButtonProps {
  variant?: 'primary' | 'secondary';
  children: React.ReactNode;
  onClick?: () => void;
}

export function Button({ variant = 'primary', children, onClick }: ButtonProps) {
  return (
    <button
      className={`px-4 py-2 rounded ${variant === 'primary' ? 'bg-blue-600 text-white' : 'bg-gray-200 text-gray-800'}`}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
```

### Styling with Tailwind

- Use Tailwind utility classes for styling
- Create custom components for repeated patterns
- Use dark mode variants: `dark:bg-gray-900`
- Follow responsive design: `sm:text-lg md:text-xl lg:text-2xl`

### API Integration

- Use Next.js API routes for backend communication
- Implement proper error handling and loading states
- Use TypeScript interfaces for API responses

```typescript
// types/api.ts
export interface EvaluationRun {
  id: string;
  name: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  metrics: Record<string, number>;
  createdAt: string;
}
```

## Architecture Decisions

### UI-First Design Philosophy

This frontend is designed to transition developers from code-based evaluation to UI-driven evaluation:

1. **Configuration UI**: Visual forms for setting up evaluations
2. **Real-time Progress**: Live updates during evaluation runs
3. **Comparison Views**: Side-by-side run comparisons with diffs
4. **Interactive Analysis**: Drill-down capabilities for detailed results

### Developer-Focused UX

- **Technical Interface**: Clean, minimal design inspired by GitHub/Vercel
- **Data-Dense Views**: Tables, charts, and detailed metrics
- **Keyboard Navigation**: Efficient workflows for power users
- **Integration Ready**: APIs for CI/CD and automation workflows

### Performance Considerations

- **Next.js App Router**: Modern routing with streaming and layouts
- **Code Splitting**: Automatic optimization for faster loading
- **Image Optimization**: Built-in Next.js image optimization
- **Caching**: Proper cache headers and static generation where possible

## Integration with Backend

The frontend connects to the Python LLM-Eval backend through:

- **REST API**: For CRUD operations on runs, datasets, and configurations
- **WebSocket**: For real-time progress updates during evaluations
- **File Uploads**: For dataset uploads and result exports

## Sprint 2 Roadmap

Current development focus for Sprint 2:

1. **Run Management UI**: Dashboard for viewing and organizing evaluation runs
2. **Comparison Interface**: Side-by-side run comparison with diff highlighting
3. **Configuration Forms**: UI for setting up evaluations without code
4. **Real-time Updates**: Live progress tracking and result streaming

## Contributing

1. **Code Formatting**: Run `npm run format` before committing
2. **Type Safety**: Ensure `npm run type-check` passes
3. **Linting**: Fix all ESLint warnings with `npm run lint:fix`
4. **Testing**: Add tests for new components and features

## Environment Variables

Create a `.env.local` file for development:

```bash
# Backend API URL
NEXT_PUBLIC_API_URL=http://localhost:8000

# Enable development features
NEXT_PUBLIC_DEV_MODE=true
```

## Deployment

The application is configured for deployment on Vercel:

```bash
npm run build  # Build for production
npm run start  # Start production server
```

## Browser Support

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

---

**Version**: v0.3.0  
**Built for**: Technical developers and ML engineers  
**Design Philosophy**: GitHub for AI Evaluation
