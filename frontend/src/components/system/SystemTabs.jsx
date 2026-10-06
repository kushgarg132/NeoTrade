import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Tabs } from '../doc/Doc';
import { HANDBOOK_TABS } from '../../utils/handbook';

/** The handbook's sections plus the Future backlog, one strip on both pages. */
const SystemTabs = ({ active, onSelect }) => {
  const navigate = useNavigate();
  const select = (id) => {
    if (id === 'future') navigate('/system/future');
    else if (onSelect) onSelect(id);
    else navigate(id === 'system' ? '/system' : `/system?tab=${id}`);
  };
  return <Tabs tabs={[...HANDBOOK_TABS, { id: 'future', label: 'Future' }]} active={active} onSelect={select} label="Handbook" />;
};

export default SystemTabs;
