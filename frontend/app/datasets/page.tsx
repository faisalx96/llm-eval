'use client';

import React from 'react';
import { Container } from '@/components/layout/container';
import { DatasetBrowser } from '@/components/ui/dataset-browser';

export default function DatasetsPage() {
  return (
    <Container>
      <div className="space-y-6">
        <DatasetBrowser />
      </div>
    </Container>
  );
}