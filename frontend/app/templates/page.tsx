'use client';

import React from 'react';
import { Container } from '@/components/layout/container';
import { TemplateMarketplace } from '@/components/ui/template-marketplace';

export default function TemplatesPage() {
  return (
    <Container>
      <div className="space-y-6">
        <TemplateMarketplace />
      </div>
    </Container>
  );
}