-- Preview SQL NON ESECUTIVA: bonifica dataset sospetti
-- Applicare solo dopo validazione manuale del cliente.
-- Scope: all
-- Numero record nello scope: 59

-- 1) Preview record target
SELECT id, fonte_id, titolo, link_bando FROM public.bando WHERE id IN (3, 5, 6, 7, 8, 35, 36, 41, 43, 44, 45, 46, 73, 74, 105, 116, 119, 122, 126, 131, 139, 142, 152, 171, 172, 177, 184, 196, 197, 199, 228, 237, 238, 239, 240, 241, 242, 243, 244, 245, 251, 252, 254, 256, 257, 258, 259, 265, 283, 284, 286, 288, 289, 290, 291, 297, 330, 331, 333) ORDER BY id;

-- 2) Esempio UPDATE soft-delete logico (da eseguire solo dopo conferma)
-- UPDATE public.bando SET stato_processing = 'failed_final', last_error_type = 'non_pertinente_dataset', last_error_message = 'Bonifica Go-Live validata manualmente' WHERE id IN (3, 5, 6, 7, 8, 35, 36, 41, 43, 44, 45, 46, 73, 74, 105, 116, 119, 122, 126, 131, 139, 142, 152, 171, 172, 177, 184, 196, 197, 199, 228, 237, 238, 239, 240, 241, 242, 243, 244, 245, 251, 252, 254, 256, 257, 258, 259, 265, 283, 284, 286, 288, 289, 290, 291, 297, 330, 331, 333);

-- 3) Esempio hard-delete (sconsigliato, solo con decisione esplicita)
-- DELETE FROM public.bando WHERE id IN (3, 5, 6, 7, 8, 35, 36, 41, 43, 44, 45, 46, 73, 74, 105, 116, 119, 122, 126, 131, 139, 142, 152, 171, 172, 177, 184, 196, 197, 199, 228, 237, 238, 239, 240, 241, 242, 243, 244, 245, 251, 252, 254, 256, 257, 258, 259, 265, 283, 284, 286, 288, 289, 290, 291, 297, 330, 331, 333);