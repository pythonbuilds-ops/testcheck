import { useState } from 'react'
import { ThemeProvider, useTheme } from './components/ThemeProvider'
import { OpeningAnimation } from './components/OpeningAnimation'
import { AgentInterface } from './components/AgentInterface'

function AppContent() {
  const { showIntro: introEnabled } = useTheme();
  const [showIntro, setShowIntro] = useState(introEnabled);

  return (
    <>
      {showIntro && (
        <OpeningAnimation onComplete={() => setShowIntro(false)} />
      )}
      {!showIntro && (
        <AgentInterface />
      )}
    </>
  );
}

function App() {
  return (
    <ThemeProvider>
      <AppContent />
    </ThemeProvider>
  )
}

export default App
