import base64
import io
import unittest

from app import app, format_violation_display, extract_product_metadata, prepare_image_for_ocr, generate_compliance_analysis, save_complaint_record, get_complaint_records, seed_demo_complaints, normalize_product_name


class HistoryRouteTest(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        self.client = app.test_client()

    def test_history_requires_login(self):
        response = self.client.get('/history', follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Login', response.data)

    def test_history_page_loads_after_login(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True
            session['username'] = 'admin'

        response = self.client.get('/history')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Inspection History', response.data)

    def test_upload_adds_record_to_history(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True
            session['username'] = 'admin'

        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0cIDATx\x9cc``\x00\x00\x00\x02\x00\x01\xe5\x27\xd8\xcf\x00\x00\x00\x00IEND\xaeB`\x82'
        )

        response = self.client.post(
            '/upload',
            data={'image': (io.BytesIO(png_bytes), 'sample.png'), 'image_type': 'front'},
            content_type='multipart/form-data',
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertIn('analysis', payload)
        self.assertIn('score', payload['analysis'])
        self.assertIn('status', payload['analysis'])

        with self.client.session_transaction() as session:
            self.assertIn('inspections', session)
            self.assertEqual(len(session['inspections']), 1)
            self.assertEqual(session['inspections'][0]['image_type'], 'front')
            self.assertIn('status', session['inspections'][0])
            self.assertIn('score', session['inspections'][0])

    def test_dashboard_uses_session_inspections_for_stats(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True
            session['username'] = 'admin'
            session['inspections'] = [
                {'status': 'COMPLIANT'},
                {'status': 'COMPLIANT'},
                {'status': 'REVIEW REQUIRED'},
                {'status': 'POTENTIAL VIOLATION'},
            ]

        response = self.client.get('/dashboard')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<p class="metric-value" style="color: #0d6efd;">4</p>', response.data)
        self.assertIn(b'<p class="metric-value" style="color: #198754;">2</p>', response.data)
        self.assertIn(b'<p class="metric-value" style="color: #ffc107;">1</p>', response.data)
        self.assertIn(b'<p class="metric-value" style="color: #dc3545;">1</p>', response.data)

    def test_inspection_detail_page_loads(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True
            session['username'] = 'admin'
            session['inspections'] = [{
                'id': 'SMQ-DETAIL-1',
                'date': '2026-09-12',
                'product': 'Front Product',
                'status': 'COMPLIANT',
                'score': 92,
                'inspector': 'admin',
                'result': 'Mandatory declarations present.',
                'findings': ['Mandatory declarations present'],
            }]

        response = self.client.get('/inspection/SMQ-DETAIL-1')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Inspection Details', response.data)
        self.assertIn(b'Front Product', response.data)
        self.assertIn(b'COMPLIANT', response.data)

    def test_result_route_loads_demo_inspection_record(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True
            session['username'] = 'admin'

        response = self.client.get('/result/SMQ-1001')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Inspection Details', response.data)
        self.assertIn(b'Rice Pack 5kg', response.data)
        self.assertIn(b'Inspection Record', response.data)

    def test_dashboard_and_history_link_to_detail_pages(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True
            session['username'] = 'admin'
            session['inspections'] = [{
                'id': 'SMQ-DETAIL-1',
                'date': '2026-09-12',
                'product': 'Front Product',
                'status': 'COMPLIANT',
                'score': 92,
                'inspector': 'admin',
                'result': 'Mandatory declarations present.',
                'findings': ['Mandatory declarations present'],
            }]

        dashboard_response = self.client.get('/dashboard')
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertIn(b'/inspection/SMQ-DETAIL-1', dashboard_response.data)

        history_response = self.client.get('/history')
        self.assertEqual(history_response.status_code, 200)
        self.assertIn(b'/inspection/SMQ-DETAIL-1', history_response.data)

    def test_dashboard_uses_readable_default_issue_labels(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True
            session['username'] = 'admin'
            session['inspections'] = []

        response = self.client.get('/dashboard')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Missing Information', response.data)
        self.assertIn(b'MRP Problem', response.data)
        self.assertIn(b'Date Problem', response.data)
        self.assertNotIn(b'Other Issue', response.data.split(b'Common Problems')[1][:500])

    def test_upload_records_multilingual_evidence_fields(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True
            session['username'] = 'admin'

        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0cIDATx\x9cc``\x00\x00\x00\x02\x00\x01\xe5\x27\xd8\xcf\x00\x00\x00\x00IEND\xaeB`\x82'
        )

        response = self.client.post(
            '/upload',
            data={'image': (io.BytesIO(png_bytes), 'sample.png'), 'image_type': 'front', 'language': 'eng+hin'},
            content_type='multipart/form-data',
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertEqual(payload['inspection']['language'], 'eng+hin')
        self.assertIn('inspection_id', payload['inspection'])
        self.assertIn('evidence_hash', payload['inspection'])
        self.assertIn('audit_events', payload['inspection'])

    def test_detail_page_displays_evidence_and_audit_sections(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True
            session['username'] = 'admin'
            session['inspections'] = [{
                'id': 'SMQ-DETAIL-2',
                'inspection_id': 'SMQ-20260912-0002',
                'date': '2026-09-12',
                'time': '17:32',
                'product': 'Front Product',
                'status': 'REVIEW REQUIRED',
                'score': 82,
                'inspector': 'admin',
                'result': 'Mandatory declarations present.',
                'findings': ['Consumer care details not detected'],
                'language': 'English + Hindi',
                'ocr_text': 'Mfg. date and MRP may be hard to read.',
                'extracted_data': {'product': 'Front Product'},
                'evidence_hash': 'abc123',
                'audit_events': [{'event_type': 'OCR Completed', 'description': 'OCR completed'}],
                'image_path': '/uploads/demo.png',
                'filename': 'demo.png',
            }]

        response = self.client.get('/inspection/SMQ-DETAIL-2')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Evidence Integrity', response.data)
        self.assertIn(b'Audit Trail', response.data)
        self.assertIn(b'OCR Result', response.data)
        self.assertIn(b'SHA-256', response.data)

    def test_violation_display_uses_user_friendly_labels(self):
        display = format_violation_display('R003')
        self.assertEqual(display['category'], 'MRP Problem')
        self.assertIn('MRP', display['detail'])
        self.assertIn('verify the mrp', display['action'].lower())

        display = format_violation_display('Consumer care details not detected')
        self.assertEqual(display['category'], 'Consumer Care Problem')
        self.assertIn('consumer care', display['detail'].lower())

    def test_normalize_product_name_replaces_ocr_failure_summary(self):
        self.assertEqual(normalize_product_name('OCR quality was insufficient to make a reliable decision.', 'front'), 'Front Product')
        self.assertEqual(normalize_product_name('No label text detected on the image.', 'front'), 'Front Product')

    def test_extract_product_metadata_requires_mrp_keyword(self):
        text = 'Price list ₹95.00 / 0.11/g'
        extracted = extract_product_metadata(text)
        self.assertIsNone(extracted.get('mrp'))

    def test_extract_product_metadata_handles_label_fields(self):
        text = (
            'AASHIRVAAD ATTA\n'
            'Manufactured by Aashirvaad Foods\n'
            'Net Quantity 5 kg\n'
            'M.R.P. ₹95.00\n'
            'Mfd 02/01/2024\n'
            'Consumer Care 1800-123-4567\n'
            'Country of Origin India'
        )
        extracted = extract_product_metadata(text, 'front')
        self.assertEqual(extracted['product_name'], 'Front Product')
        self.assertIn('Aashirvaad', extracted['manufacturer'])
        self.assertIn('5', extracted['quantity'])
        self.assertEqual(extracted['mrp'], '95.00')
        self.assertIn('02/01/2024', extracted['mfg_date'])
        self.assertIn('1800', extracted['care_instructions'])
        self.assertIn('India', extracted['origin'])

    def test_prepare_image_for_ocr_creates_processed_copy(self):
        image = Image.new('RGB', (120, 80), color='white')
        image_path = 'tmp_test_label.png'
        image.save(image_path)
        try:
            processed_path = prepare_image_for_ocr(image_path)
            self.assertTrue(processed_path)
            self.assertTrue(processed_path != image_path)
            self.assertTrue(processed_path.endswith('.png'))
        finally:
            if os.path.exists(image_path):
                os.remove(image_path)
            if os.path.exists(processed_path):
                os.remove(processed_path)

    def test_low_confidence_ocr_stays_review_required(self):
        analysis = generate_compliance_analysis('front', 'Text could not be clearly detected. Manual verification required.', {'product_name': 'Sample'}, {'confidence': 18.0})
        self.assertEqual(analysis['status'], 'REVIEW REQUIRED')

    def test_complaint_storage_appends_multiple_records(self):
        base_count = len(get_complaint_records())
        complaint_a = {'complaint_id': 'CMP-TEST-0001', 'consumer': 'consumer', 'product_name': 'Product A', 'status': 'SUBMITTED', 'description': 'Test A'}
        complaint_b = {'complaint_id': 'CMP-TEST-0002', 'consumer': 'consumer', 'product_name': 'Product B', 'status': 'SUBMITTED', 'description': 'Test B'}
        save_complaint_record(complaint_a)
        save_complaint_record(complaint_b)
        records = get_complaint_records()
        self.assertGreaterEqual(len(records), base_count + 2)
        self.assertTrue(any(item.get('complaint_id') == 'CMP-TEST-0001' for item in records))
        self.assertTrue(any(item.get('complaint_id') == 'CMP-TEST-0002' for item in records))

    def test_seed_demo_complaints_does_not_remove_existing_records(self):
        initial = len(get_complaint_records())
        seed_demo_complaints()
        after_seed = len(get_complaint_records())
        self.assertGreaterEqual(after_seed, initial + 3)

    def test_upload_returns_result_redirect_for_analysis_page(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True
            session['username'] = 'admin'

        png_bytes = (
            b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
            b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0cIDATx\x9cc``\x00\x00\x00\x02\x00\x01\xe5\x27\xd8\xcf\x00\x00\x00\x00IEND\xaeB`\x82'
        )

        response = self.client.post(
            '/upload',
            data={'image': (io.BytesIO(png_bytes), 'sample.png'), 'image_type': 'front'},
            content_type='multipart/form-data',
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload['success'])
        self.assertIn('redirect_url', payload)
        self.assertTrue(payload['redirect_url'].startswith('/result/'))
        self.assertIn(payload['inspection']['inspection_id'], payload['redirect_url'])

        detail_response = self.client.get(payload['redirect_url'])
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn(b'Inspection Details', detail_response.data)

    def test_consumer_can_submit_multiple_complaints_without_relogin(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True
            session['username'] = 'consumer'
            session['user_role'] = 'consumer'

        before = len(get_complaint_records('consumer'))
        complaint_ids = []
        for i in range(1, 4):
            response = self.client.post(
                '/consumer/complaint/new',
                data={
                    'product_name': f'Product {i}',
                    'complaint_description': f'Complaint {i}',
                    'language': 'eng',
                },
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 302)
            complaint_ids.append(response.headers.get('Location').rsplit('/', 1)[-1])

            with self.client.session_transaction() as session:
                self.assertTrue(session.get('logged_in'))
                self.assertEqual(session.get('username'), 'consumer')

        after = get_complaint_records('consumer')
        self.assertGreaterEqual(len(after), before + 3)
        self.assertEqual(len(complaint_ids), len(set(complaint_ids)))
        self.assertTrue(all(any(item.get('complaint_id') == cid for item in after) for cid in complaint_ids))

    def test_default_demo_cases_persist_after_real_complaint_submission(self):
        with self.client.session_transaction() as session:
            session['logged_in'] = True
            session['username'] = 'consumer'
            session['user_role'] = 'consumer'

        initial_total = len(get_complaint_records())
        initial_demo = len(get_complaint_records('consumer'))

        self.client.post(
            '/consumer/complaint/new',
            data={
                'product_name': 'Persisted Product',
                'complaint_description': 'Persisted complaint',
                'language': 'eng',
            },
            follow_redirects=False,
        )

        records = get_complaint_records()
        consumer_records = get_complaint_records('consumer')
        self.assertGreaterEqual(len(records), initial_total + 1)
        self.assertGreaterEqual(len(consumer_records), initial_demo + 1)
        self.assertTrue(any(item.get('product_name') == 'Persisted Product' for item in records))


if __name__ == '__main__':
    unittest.main()
