import React from 'react';
import { cn } from '@/lib/utils';

// Grid container component
export interface GridProps {
  children: React.ReactNode;
  cols?: 1 | 2 | 3 | 4 | 5 | 6 | 12;
  gap?: 'none' | 'sm' | 'md' | 'lg' | 'xl';
  responsive?: {
    sm?: 1 | 2 | 3 | 4 | 5 | 6 | 12;
    md?: 1 | 2 | 3 | 4 | 5 | 6 | 12;
    lg?: 1 | 2 | 3 | 4 | 5 | 6 | 12;
    xl?: 1 | 2 | 3 | 4 | 5 | 6 | 12;
  };
  className?: string;
}

const Grid: React.FC<GridProps> = ({
  children,
  cols = 1,
  gap = 'md',
  responsive,
  className,
}) => {
  const getColsClasses = () => {
    const colsMap = {
      1: 'grid-cols-1',
      2: 'grid-cols-2',
      3: 'grid-cols-3',
      4: 'grid-cols-4',
      5: 'grid-cols-5',
      6: 'grid-cols-6',
      12: 'grid-cols-12',
    };
    return colsMap[cols];
  };

  const getGapClasses = () => {
    const gapMap = {
      none: 'gap-0',
      sm: 'gap-2',
      md: 'gap-4',
      lg: 'gap-6',
      xl: 'gap-8',
    };
    return gapMap[gap];
  };

  const getResponsiveClasses = () => {
    if (!responsive) return '';

    const classes = [];

    if (responsive.sm) {
      const colsMap = {
        1: 'sm:grid-cols-1',
        2: 'sm:grid-cols-2',
        3: 'sm:grid-cols-3',
        4: 'sm:grid-cols-4',
        5: 'sm:grid-cols-5',
        6: 'sm:grid-cols-6',
        12: 'sm:grid-cols-12',
      };
      classes.push(colsMap[responsive.sm]);
    }

    if (responsive.md) {
      const colsMap = {
        1: 'md:grid-cols-1',
        2: 'md:grid-cols-2',
        3: 'md:grid-cols-3',
        4: 'md:grid-cols-4',
        5: 'md:grid-cols-5',
        6: 'md:grid-cols-6',
        12: 'md:grid-cols-12',
      };
      classes.push(colsMap[responsive.md]);
    }

    if (responsive.lg) {
      const colsMap = {
        1: 'lg:grid-cols-1',
        2: 'lg:grid-cols-2',
        3: 'lg:grid-cols-3',
        4: 'lg:grid-cols-4',
        5: 'lg:grid-cols-5',
        6: 'lg:grid-cols-6',
        12: 'lg:grid-cols-12',
      };
      classes.push(colsMap[responsive.lg]);
    }

    if (responsive.xl) {
      const colsMap = {
        1: 'xl:grid-cols-1',
        2: 'xl:grid-cols-2',
        3: 'xl:grid-cols-3',
        4: 'xl:grid-cols-4',
        5: 'xl:grid-cols-5',
        6: 'xl:grid-cols-6',
        12: 'xl:grid-cols-12',
      };
      classes.push(colsMap[responsive.xl]);
    }

    return classes.join(' ');
  };

  return (
    <div
      className={cn(
        'grid',
        getColsClasses(),
        getGapClasses(),
        getResponsiveClasses(),
        className
      )}
    >
      {children}
    </div>
  );
};

// Grid item component
export interface GridItemProps {
  children: React.ReactNode;
  colSpan?: 1 | 2 | 3 | 4 | 5 | 6 | 12;
  rowSpan?: 1 | 2 | 3 | 4 | 5 | 6;
  colStart?: 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12;
  colEnd?: 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13;
  responsive?: {
    sm?: { colSpan?: 1 | 2 | 3 | 4 | 5 | 6 | 12 };
    md?: { colSpan?: 1 | 2 | 3 | 4 | 5 | 6 | 12 };
    lg?: { colSpan?: 1 | 2 | 3 | 4 | 5 | 6 | 12 };
    xl?: { colSpan?: 1 | 2 | 3 | 4 | 5 | 6 | 12 };
  };
  className?: string;
}

const GridItem: React.FC<GridItemProps> = ({
  children,
  colSpan,
  rowSpan,
  colStart,
  colEnd,
  responsive,
  className,
}) => {
  const getColSpanClasses = () => {
    if (!colSpan) return '';
    const spanMap = {
      1: 'col-span-1',
      2: 'col-span-2',
      3: 'col-span-3',
      4: 'col-span-4',
      5: 'col-span-5',
      6: 'col-span-6',
      12: 'col-span-12',
    };
    return spanMap[colSpan];
  };

  const getRowSpanClasses = () => {
    if (!rowSpan) return '';
    const spanMap = {
      1: 'row-span-1',
      2: 'row-span-2',
      3: 'row-span-3',
      4: 'row-span-4',
      5: 'row-span-5',
      6: 'row-span-6',
    };
    return spanMap[rowSpan];
  };

  const getColStartClasses = () => {
    if (!colStart) return '';
    const startMap = {
      1: 'col-start-1',
      2: 'col-start-2',
      3: 'col-start-3',
      4: 'col-start-4',
      5: 'col-start-5',
      6: 'col-start-6',
      7: 'col-start-7',
      8: 'col-start-8',
      9: 'col-start-9',
      10: 'col-start-10',
      11: 'col-start-11',
      12: 'col-start-12',
    };
    return startMap[colStart];
  };

  const getColEndClasses = () => {
    if (!colEnd) return '';
    const endMap = {
      1: 'col-end-1',
      2: 'col-end-2',
      3: 'col-end-3',
      4: 'col-end-4',
      5: 'col-end-5',
      6: 'col-end-6',
      7: 'col-end-7',
      8: 'col-end-8',
      9: 'col-end-9',
      10: 'col-end-10',
      11: 'col-end-11',
      12: 'col-end-12',
      13: 'col-end-13',
    };
    return endMap[colEnd];
  };

  const getResponsiveClasses = () => {
    if (!responsive) return '';

    const classes = [];

    if (responsive.sm?.colSpan) {
      const spanMap = {
        1: 'sm:col-span-1',
        2: 'sm:col-span-2',
        3: 'sm:col-span-3',
        4: 'sm:col-span-4',
        5: 'sm:col-span-5',
        6: 'sm:col-span-6',
        12: 'sm:col-span-12',
      };
      classes.push(spanMap[responsive.sm.colSpan]);
    }

    if (responsive.md?.colSpan) {
      const spanMap = {
        1: 'md:col-span-1',
        2: 'md:col-span-2',
        3: 'md:col-span-3',
        4: 'md:col-span-4',
        5: 'md:col-span-5',
        6: 'md:col-span-6',
        12: 'md:col-span-12',
      };
      classes.push(spanMap[responsive.md.colSpan]);
    }

    if (responsive.lg?.colSpan) {
      const spanMap = {
        1: 'lg:col-span-1',
        2: 'lg:col-span-2',
        3: 'lg:col-span-3',
        4: 'lg:col-span-4',
        5: 'lg:col-span-5',
        6: 'lg:col-span-6',
        12: 'lg:col-span-12',
      };
      classes.push(spanMap[responsive.lg.colSpan]);
    }

    if (responsive.xl?.colSpan) {
      const spanMap = {
        1: 'xl:col-span-1',
        2: 'xl:col-span-2',
        3: 'xl:col-span-3',
        4: 'xl:col-span-4',
        5: 'xl:col-span-5',
        6: 'xl:col-span-6',
        12: 'xl:col-span-12',
      };
      classes.push(spanMap[responsive.xl.colSpan]);
    }

    return classes.join(' ');
  };

  return (
    <div
      className={cn(
        getColSpanClasses(),
        getRowSpanClasses(),
        getColStartClasses(),
        getColEndClasses(),
        getResponsiveClasses(),
        className
      )}
    >
      {children}
    </div>
  );
};

// Flex layout component
export interface FlexProps {
  children: React.ReactNode;
  direction?: 'row' | 'row-reverse' | 'col' | 'col-reverse';
  align?: 'start' | 'center' | 'end' | 'stretch' | 'baseline';
  justify?: 'start' | 'center' | 'end' | 'between' | 'around' | 'evenly';
  wrap?: 'nowrap' | 'wrap' | 'wrap-reverse';
  gap?: 'none' | 'sm' | 'md' | 'lg' | 'xl';
  className?: string;
}

const Flex: React.FC<FlexProps> = ({
  children,
  direction = 'row',
  align = 'start',
  justify = 'start',
  wrap = 'nowrap',
  gap = 'none',
  className,
}) => {
  const getDirectionClasses = () => {
    const directionMap = {
      row: 'flex-row',
      'row-reverse': 'flex-row-reverse',
      col: 'flex-col',
      'col-reverse': 'flex-col-reverse',
    };
    return directionMap[direction];
  };

  const getAlignClasses = () => {
    const alignMap = {
      start: 'items-start',
      center: 'items-center',
      end: 'items-end',
      stretch: 'items-stretch',
      baseline: 'items-baseline',
    };
    return alignMap[align];
  };

  const getJustifyClasses = () => {
    const justifyMap = {
      start: 'justify-start',
      center: 'justify-center',
      end: 'justify-end',
      between: 'justify-between',
      around: 'justify-around',
      evenly: 'justify-evenly',
    };
    return justifyMap[justify];
  };

  const getWrapClasses = () => {
    const wrapMap = {
      nowrap: 'flex-nowrap',
      wrap: 'flex-wrap',
      'wrap-reverse': 'flex-wrap-reverse',
    };
    return wrapMap[wrap];
  };

  const getGapClasses = () => {
    const gapMap = {
      none: 'gap-0',
      sm: 'gap-2',
      md: 'gap-4',
      lg: 'gap-6',
      xl: 'gap-8',
    };
    return gapMap[gap];
  };

  return (
    <div
      className={cn(
        'flex',
        getDirectionClasses(),
        getAlignClasses(),
        getJustifyClasses(),
        getWrapClasses(),
        getGapClasses(),
        className
      )}
    >
      {children}
    </div>
  );
};

export { Grid, GridItem, Flex };
