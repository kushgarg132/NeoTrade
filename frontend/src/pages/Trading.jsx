import React, { useEffect, useState } from 'react';
import Layout from '../components/Layout';
import PaperShell from '../components/paper/PaperShell';
import { paperPositions } from '../utils/books';
import { Sheet, Statement, Row, Cell, Money, Empty, Ruling, NetLine, Scrip } from '../components/doc/Doc';
import { Badge } from '../components/common/Badge';
import api, { endpoints } from '../utils/api';
import { useTopic } from '../hooks/useStream';
import { formatCurrency, formatQuantity, formatClock } from '../utils/formatters';

/** The paper positions and raw executions. Run controls moved to the Practice overview. */
const Trading = () => {
  const [positions, setPositions] = useState({});
  const [fills, setFills] = useState([]);
  const [loading, setLoading] = useState(true);

  const loadLedger = () =>
    Promise.all([api.get(endpoints.trading.positions('paper')), api.get(endpoints.trading.fills('paper'))])
      .then(([positionsRes, fillsRes]) => {
        setPositions(positionsRes.data);
        setFills(fillsRes.data);
      })
      .catch(() => {});

  useEffect(() => {
    loadLedger().finally(() => setLoading(false));
  }, []);

  useTopic('positions', (message) => setPositions(paperPositions(message.data)));
  useTopic('trades', loadLedger);

  const openPositions = Object.values(positions);
  const realised = openPositions.reduce((total, p) => total + (p.realized_pnl || 0), 0);
  const recentFills = [...fills]
    .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
    .slice(0, 25);

  return (
    <Layout>
      <PaperShell>
        <Sheet title="Positions" meta={`${openPositions.length} open`}>
          {loading ? (
            <Ruling rows={3} />
          ) : openPositions.length === 0 ? (
            <Empty title="Flat" detail="No open position on the book." />
          ) : (
            <>
              <Statement
                columns={[
                  { key: 'scrip', label: 'Scrip' },
                  { key: 'qty', label: 'Qty', align: 'right' },
                  { key: 'avg', label: 'Avg', align: 'right' },
                  { key: 'realised', label: 'Realised', align: 'right' },
                ]}
              >
                {openPositions.map((position) => (
                  <Row key={position.symbol}>
                    <Cell>
                      <Scrip symbol={position.symbol} />
                    </Cell>
                    <Cell align="right" mono>
                      {formatQuantity(position.quantity)}
                    </Cell>
                    <Cell align="right" mono>
                      {formatCurrency(position.avg_price)}
                    </Cell>
                    <Cell align="right">
                      <Money value={position.realized_pnl} />
                    </Cell>
                  </Row>
                ))}
              </Statement>
              <NetLine label="Realised on open scrip">
                <Money value={realised} />
              </NetLine>
            </>
          )}
        </Sheet>

        <Sheet title="Executions" meta={`${fills.length} fills`}>
          {loading ? (
            <Ruling rows={3} />
          ) : recentFills.length === 0 ? (
            <Empty title="No executions yet" detail="Fills appear here as orders are filled." />
          ) : (
            <Statement
              columns={[
                { key: 'scrip', label: 'Scrip' },
                { key: 'time', label: 'Time' },
                { key: 'side', label: 'Side' },
                { key: 'qty', label: 'Qty', align: 'right' },
                { key: 'price', label: 'Price', align: 'right' },
                { key: 'costs', label: 'Charges', align: 'right' },
              ]}
            >
              {recentFills.map((fill) => (
                <Row key={`${fill.order_id}-${fill.timestamp}`}>
                  <Cell>
                    <Scrip symbol={fill.symbol} />
                  </Cell>
                  <Cell className="doc-meta normal-case">{formatClock(fill.timestamp)}</Cell>
                  <Cell>
                    <Badge variant={fill.side === 'BUY' ? 'success' : 'destructive'}>
                      {fill.side}
                    </Badge>
                  </Cell>
                  <Cell align="right" mono>
                    {formatQuantity(fill.quantity)}
                  </Cell>
                  <Cell align="right" mono>
                    {formatCurrency(fill.price)}
                  </Cell>
                  <Cell align="right" mono className="text-[var(--ink-faint)]">
                    {formatCurrency(fill.costs)}
                  </Cell>
                </Row>
              ))}
            </Statement>
          )}
        </Sheet>
      </PaperShell>
    </Layout>
  );
};

export default Trading;
