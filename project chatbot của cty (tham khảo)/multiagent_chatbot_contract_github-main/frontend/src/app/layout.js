import '../styles/global.css';
import { ToastContainer } from 'react-toastify';
import 'react-toastify/dist/ReactToastify.css';
import ClientOnly from '../components/ClientOnly';
import HeartbeatProvider from '../components/HeartbeatProvider';
import { ThemeProvider } from '../components/ThemeProvider';
import BootLoader from '../components/BootLoader';
import InteractionFX from '../components/InteractionFX';

export const metadata = {
  title: 'NTC - AI Chatbot',
  description: 'Modern AI workspace for RAG and contract automation.',
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <link rel="icon" href="/snowflake.png" type="image/png" />
        <script
          dangerouslySetInnerHTML={{
            __html: `
              (function () {
                try {
                  var t = localStorage.getItem('theme') || 'system';
                  var isDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
                  var r = t === 'system' ? (isDark ? 'dark' : 'light') : t;
                  document.documentElement.setAttribute('data-theme', r);
                } catch (_) {}
              })();
            `,
          }}
        />
      </head>
      <body suppressHydrationWarning>
        <ClientOnly>
          <ThemeProvider>
            <BootLoader />
            <InteractionFX />
            <main className="appShell" suppressHydrationWarning>
              <HeartbeatProvider>{children}</HeartbeatProvider>
            </main>
            <ToastContainer
              position="bottom-right"
              autoClose={2500}
              hideProgressBar={false}
              newestOnTop
              closeOnClick
              pauseOnFocusLoss
              draggable
              pauseOnHover
              theme="colored"
            />
          </ThemeProvider>
        </ClientOnly>
      </body>
    </html>
  );
}
