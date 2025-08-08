import React from 'react';
import { cn } from '@/lib/utils';

export interface ContainerProps {
  children: React.ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl' | 'full';
  padding?: 'none' | 'sm' | 'md' | 'lg';
  className?: string;
}

const Container: React.FC<ContainerProps> = ({
  children,
  size = 'lg',
  padding = 'md',
  className,
}) => {
  const getSizeClasses = () => {
    switch (size) {
      case 'sm':
        return 'max-w-2xl';
      case 'md':
        return 'max-w-4xl';
      case 'lg':
        return 'max-w-6xl';
      case 'xl':
        return 'max-w-7xl';
      case 'full':
        return 'max-w-full';
      default:
        return 'max-w-6xl';
    }
  };

  const getPaddingClasses = () => {
    switch (padding) {
      case 'none':
        return '';
      case 'sm':
        return 'px-4 py-2';
      case 'md':
        return 'px-6 py-4';
      case 'lg':
        return 'px-8 py-6';
      default:
        return 'px-6 py-4';
    }
  };

  return (
    <div
      className={cn(
        'mx-auto w-full',
        getSizeClasses(),
        getPaddingClasses(),
        className
      )}
    >
      {children}
    </div>
  );
};

export { Container };
