// Minimal layout for the setup wizard — no header, no navigation.
// The wizard must be usable before Discord auth and the rest of the app is configured.
export default function SetupLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background flex flex-col">
      {children}
    </div>
  );
}
