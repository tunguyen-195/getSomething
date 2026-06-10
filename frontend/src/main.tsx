import React from 'react';
import ReactDOM from 'react-dom/client';
import createCache from '@emotion/cache';
import { CacheProvider } from '@emotion/react';
import App from './App';
import '@fontsource/roboto/300.css';
import '@fontsource/roboto/400.css';
import '@fontsource/roboto/500.css';
import '@fontsource/roboto/700.css';

const cspNonceMeta = document.querySelector<HTMLMetaElement>('meta[name="csp-nonce"]');
const cspNonce = cspNonceMeta?.content && cspNonceMeta.content !== '__CSP_NONCE__'
  ? cspNonceMeta.content
  : undefined;

const emotionCache = createCache({
  key: 'mui',
  nonce: cspNonce,
  prepend: true,
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <CacheProvider value={emotionCache}>
      <App />
    </CacheProvider>
  </React.StrictMode>
);
