import { Route, Routes } from 'react-router-dom'

import { Layout } from './components/Layout'
import { ProtectedRoute } from './components/ProtectedRoute'
import { Browse } from './pages/Browse'
import { CreateListing } from './pages/CreateListing'
import { ListingDetail } from './pages/ListingDetail'
import { Login } from './pages/Login'
import { MyListings } from './pages/MyListings'
import { Register } from './pages/Register'
import { Wishlist } from './pages/Wishlist'

export function App(): JSX.Element {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Browse />} />
        <Route path="login" element={<Login />} />
        <Route path="register" element={<Register />} />
        <Route path="listings/:id" element={<ListingDetail />} />

        <Route element={<ProtectedRoute />}>
          <Route path="listings/new" element={<CreateListing />} />
          <Route path="my-listings" element={<MyListings />} />
          <Route path="wishlist" element={<Wishlist />} />
        </Route>

        <Route
          path="*"
          element={<p className="py-20 text-center text-slate-500">Page not found.</p>}
        />
      </Route>
    </Routes>
  )
}
