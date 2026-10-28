import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { Upload } from './Upload';
vi.mock('../shell',()=>({useApp:()=>({config:{max_upload_mb:10,max_pages:30}})}));
describe('accessible upload component',()=>{
 it('has an accessible browse control',()=>{render(<MemoryRouter><Upload/></MemoryRouter>);expect(screen.getByRole('button',{name:'Browse files'})).toBeEnabled();expect(screen.getByLabelText('Upload resume PDF, DOCX or TXT')).toHaveAttribute('accept','.pdf,.docx,.txt')});
 it('shows a clear error for an unsupported file',()=>{render(<MemoryRouter><Upload/></MemoryRouter>);fireEvent.change(screen.getByLabelText('Upload resume PDF, DOCX or TXT'),{target:{files:[new File(['file'],'resume.exe')]}});expect(screen.getByRole('alert')).toHaveTextContent('Choose a PDF, DOCX, or TXT')});
 it('rejects an empty file before a network request',()=>{render(<MemoryRouter><Upload/></MemoryRouter>);fireEvent.change(screen.getByLabelText('Upload resume PDF, DOCX or TXT'),{target:{files:[new File([],'resume.pdf')]}});expect(screen.getByRole('alert')).toHaveTextContent('empty')});
});
