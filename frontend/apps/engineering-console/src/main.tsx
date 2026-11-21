import React from 'react'
import ReactDOM from 'react-dom/client'
import { RouterProvider } from '@tanstack/react-router'
import { syncDocumentLocale } from '@shiro-mlops/shared/i18n/document-locale'
import { documentTitleFor } from './i18n/messages'
import { createAppRouter } from './router'
import './index.css'

const router = createAppRouter()

syncDocumentLocale(documentTitleFor)

const rootElement = document.getElementById('root')!
if (!rootElement.innerHTML) {
  const root = ReactDOM.createRoot(rootElement)
  root.render(
    <React.StrictMode>
      <RouterProvider router={router} />
    </React.StrictMode>,
  )
}
