export default function Loading() {
  return (
    <div className="bootLoader">
      <div className="bootAura" />
      <div className="bootCore">
        <img src="/snowflake.png" alt="NTC" width="72" height="72" className="bootLogo" />
        <p>Syncing AI workspace</p>
        <div className="bootBar"><div className="bootBarInner" /></div>
      </div>
    </div>
  );
}
