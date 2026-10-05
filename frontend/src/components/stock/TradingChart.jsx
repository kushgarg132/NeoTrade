import React, { useState } from 'react';
import { 
  AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, 
  CartesianGrid, Bar, ComposedChart, ReferenceLine 
} from 'recharts';
import { Card, CardContent, CardHeader, CardTitle } from '../common/Card';
import { formatCurrency, formatCompactNumber } from '../../utils/formatters';
import { cn } from '../../utils/cn';

const CustomTooltip = ({ active, payload, label, currency }) => {
  if (active && payload && payload.length) {
    const p = payload[0].payload;
    return (
      <div className="sheet p-3">
         <p className="text-xs text-muted-foreground mb-1">{label}</p>
         <div className="space-y-0.5">
            <div className="flex items-center gap-4 justify-between">
              <span className="text-sm font-bold text-foreground">{formatCurrency(p.price, currency)}</span>
              <span className={cn(
                  "text-xs font-medium",
                  p.close >= p.open ? "text-emerald-400" : "text-rose-400"
              )}>
                  {((p.close - p.open) / p.open * 100).toFixed(2)}%
              </span>
            </div>
            <div className="flex items-center gap-4 justify-between text-xs text-muted-foreground">
               <span>Vol:</span>
               <span className="font-mono">{formatCompactNumber(p.volume)}</span>
            </div>
         </div>
      </div>
    );
  }
  return null;
};

const TradingChart = ({ data, technicals, className, currency }) => {
  const [timeframe, setTimeframe] = useState('1Y');

  // Filter data based on timeframe
  const filteredData = React.useMemo(() => {
    if (!data) return [];
    let days = 365;
    if (timeframe === '1M') days = 22;
    if (timeframe === '3M') days = 66;
    if (timeframe === '6M') days = 132;
    
    // Slice from the end
    return data.slice(-days);
  }, [data, timeframe]);

  // Format data for Recharts
  const formattedData = filteredData.map(item => ({
    ...item,
    date: new Date(item.timestamp).toLocaleDateString('en-IN', { month: 'short', day: 'numeric', timeZone: 'Asia/Kolkata' }),
    price: Number(item.close),
    volume: Number(item.volume)
  }));

  return (
    <Card className={cn("flex flex-col h-[420px]", className)}>
        <CardHeader className="flex flex-row items-center justify-between">
            <div className="flex items-center gap-4">
                <CardTitle>Price action</CardTitle>
                <div className="flex border border-[var(--rule-strong)]">
                    {['1M', '3M', '6M', '1Y'].map(tf => (
                         <button
                            key={tf}
                            onClick={() => setTimeframe(tf)}
                            className={cn(
                                "px-2.5 py-1 font-[family-name:var(--font-narrow)] text-[0.6875rem] font-semibold uppercase tracking-[0.11em] transition-colors",
                                timeframe === tf
                                    ? "bg-[var(--ink)] text-[var(--paper)]"
                                    : "text-[var(--ink-soft)] hover:text-[var(--ink)]"
                            )}
                        >
                            {tf}
                        </button>
                    ))}
                </div>
            </div>
        </CardHeader>

        <CardContent className="flex-1 p-0 relative">
            {formattedData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={formattedData} margin={{ top: 20, right: 0, left: 0, bottom: 0 }}>
                        <defs>
                            <linearGradient id="colorPrice" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="5%" stopColor="var(--stamp)" stopOpacity={0.3}/>
                                <stop offset="95%" stopColor="var(--stamp)" stopOpacity={0}/>
                            </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" stroke="var(--rule)" vertical={false} />
                        <XAxis 
                            dataKey="date" 
                            stroke="var(--ink-faint)"
                            tick={{ fontSize: 11 }}
                            tickLine={false}
                            axisLine={false}
                            minTickGap={30}
                        />
                        <YAxis 
                            yAxisId="right"
                            orientation="right"
                            domain={['auto', 'auto']}
                            stroke="var(--ink-faint)"
                            tick={{ fontSize: 11 }}
                            tickLine={false}
                            axisLine={false}
                            tickFormatter={(val) => {
                                const locale = (currency === 'INR') ? 'en-IN' : 'en-US';
                                return new Intl.NumberFormat(locale, { style: 'currency', currency: currency || 'USD', maximumFractionDigits: 0 }).format(val);
                            }}
                            width={80}
                        />
                        <Tooltip content={(props) => <CustomTooltip {...props} currency={currency} />} cursor={{ stroke: 'var(--rule-strong)', strokeWidth: 1 }} />
                        
                        {technicals?.nearest_support && (
                             <ReferenceLine yAxisId="right" y={technicals.nearest_support} stroke="var(--gain)" strokeDasharray="5 5" label={{ value: 'SUP', fill: 'var(--gain)', fontSize: 10, position: 'insideLeft' }} />
                        )}
                        {technicals?.nearest_resistance && (
                             <ReferenceLine yAxisId="right" y={technicals.nearest_resistance} stroke="var(--loss)" strokeDasharray="5 5" label={{ value: 'RES', fill: 'var(--loss)', fontSize: 10, position: 'insideLeft' }} />
                        )}

                        <Area 
                            yAxisId="right"
                            type="monotone" 
                            dataKey="price" 
                            stroke="var(--stamp)" 
                            strokeWidth={1.5}
                            fillOpacity={1} 
                            fill="url(#colorPrice)" 
                        />
                    </ComposedChart>
                </ResponsiveContainer>
            ) : (
                <div className="flex h-full items-center justify-center text-muted-foreground">
                    No Data Available
                </div>
            )}
        </CardContent>
    </Card>
  );
};

export default TradingChart;
