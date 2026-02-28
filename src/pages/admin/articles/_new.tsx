import React from 'react';
import AdminLayout from '../../../layouts/AdminLayout';
import ArticleForm from '../../../components/ArticleForm';

export default function NewArticle() {
  return (
    <AdminLayout>
      <div className="p-6">
        <h1 className="text-2xl font-bold mb-6">New Article</h1>
        <ArticleForm />
      </div>
    </AdminLayout>
  );
}