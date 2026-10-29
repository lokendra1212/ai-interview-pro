import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';

type Props = { data: { date: string; score: number }[]; compact?: boolean; large?: boolean };

export default function ProgressChart({ data, compact = false, large = false }: Props) {
  const rows = data.map((row, index) => ({
    name: compact ? `Session ${index + 1}` : new Date(row.date).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
    score: row.score,
  }));
  const fill = large ? 'fillLarge' : 'fillScore';
  return <ResponsiveContainer width="100%" height="100%">
    <AreaChart data={rows} margin={large ? { top: 12, right: 20, left: -25, bottom: 5 } : { top: 12, right: 15, left: -25, bottom: 0 }}>
      <defs><linearGradient id={fill} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#7555d9" stopOpacity={large ? .2 : .16}/><stop offset="95%" stopColor="#7555d9" stopOpacity={0}/></linearGradient></defs>
      <CartesianGrid stroke="#ececf1" strokeDasharray="4 5" vertical={false}/>
      <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: '#9595a3' }}/>
      <YAxis domain={[0,100]} axisLine={false} tickLine={false} tick={{ fontSize: 11, fill: '#9595a3' }}/>
      <Tooltip/>
      <Area type="monotone" dataKey="score" stroke="#7657d8" strokeWidth={large ? 3 : 2.5} fill={`url(#${fill})`}/>
    </AreaChart>
  </ResponsiveContainer>;
}
