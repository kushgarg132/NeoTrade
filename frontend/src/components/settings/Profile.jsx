import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight } from 'lucide-react';
import { Avatar } from '../common/Avatar';
import api, { endpoints } from '../../utils/api';
import { useAuth } from '../../context/AuthContext';

/** Who you are (the /profile page holds the details). */
const Profile = () => {
  const { user } = useAuth();
  const [displayName, setDisplayName] = useState(null);
  useEffect(() => {
    api.get(endpoints.profile.get).then((res) => setDisplayName(res.data.profile.display_name || null)).catch(() => {});
  }, []);
  return (
    <div className="space-y-3">
      <Link to="/profile" className="flex items-center gap-3 min-h-14 rounded-[16px] border border-[var(--border)] bg-[var(--surface)] p-3">
        <Avatar src={user?.picture} name={displayName || user?.name} size={40} />
        <span className="flex-1 min-w-0">
          <span className="block text-[15px] font-semibold text-[var(--text)] truncate">{displayName || user?.name || 'Your profile'}</span>
          <span className="block text-[13px] text-[var(--text-muted)] truncate">Profile, AI instructions and memory</span>
        </span>
        <ChevronRight className="w-4 h-4 shrink-0 text-[var(--text-muted)]" aria-hidden="true" />
      </Link>
    </div>
  );
};

export default Profile;
