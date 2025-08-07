'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    // Redirect to dashboard on app load
    router.push('/dashboard');
  }, [router]);

  return (
    <div className="flex items-center justify-center min-h-screen">
      <div className="text-center">
        <div className="w-8 h-8 border-4 border-primary-600 border-t-transparent border-solid rounded-full animate-spin mx-auto mb-4" />
        <p className="text-neutral-600 dark:text-neutral-300">Redirecting to dashboard...</p>
      </div>
    </div>
  );
}
