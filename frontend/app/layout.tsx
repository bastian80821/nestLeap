import React from 'react'
import './globals.css'
import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import { Toaster } from 'react-hot-toast'
import { ThemeProvider } from '@/components/ThemeProvider'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'NestLeap',
  description: 'AI-powered financial intelligence platform with intelligent investment insights',
  keywords: 'stocks, investment, AI, analysis, recommendations, financial, nestleap',
  authors: [{ name: 'NestLeap Team' }],
  icons: {
    icon: '/logo.png',
    shortcut: '/logo.png',
    apple: '/logo.png',
  },
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.className} bg-neutral-50 dark:bg-black-900 min-h-screen transition-colors`}>
        <ThemeProvider>
        <main className="min-h-screen">
          {children}
        </main>
        <Toaster
          position="top-right"
          toastOptions={{
            duration: 4000,
            style: {
                background: 'var(--toast-bg)',
                color: 'var(--toast-color)',
              borderRadius: '12px',
                border: '1px solid var(--toast-border)',
              fontSize: '14px',
            },
            success: {
              style: {
                  background: 'var(--toast-success-bg)',
                  color: 'var(--toast-success-color)',
                  border: '1px solid var(--toast-success-border)',
              },
            },
            error: {
              style: {
                  background: 'var(--toast-error-bg)',
                  color: 'var(--toast-error-color)',
                  border: '1px solid var(--toast-error-border)',
              },
            },
          }}
        />
        </ThemeProvider>
      </body>
    </html>
  )
} 