import Link from 'next/link';
// Redirect to /query-data as homepage
import { redirect } from 'next/navigation';

export default function Page() {
  redirect('/chat');
  return null;
}

