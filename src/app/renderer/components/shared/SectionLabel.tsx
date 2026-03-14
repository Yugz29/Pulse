export default function SectionLabel({ children }: { children: string }) {
  return (
    <div style={{ fontSize: 10, color: '#4a4a52', letterSpacing: '0.14em', fontWeight: 600 }}>
      {children}
    </div>
  );
}
