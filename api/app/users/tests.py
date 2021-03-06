import json
from datetime import datetime, timedelta
import copy

from app import app, db
from app.applicationModel.models import ApplicationForm
from app.events.models import Event, EventRole
from app.organisation.models import Organisation
from app.responses.models import Response
from app.users.models import (AppUser, Country, PasswordReset, UserCategory,
                              UserComment)
from app.utils.errors import POLICY_ALREADY_AGREED, POLICY_NOT_AGREED
from app.utils.testing import ApiTestCase

USER_DATA = {
        'email': 'something@email.com',
        'firstname': 'Some',
        'lastname': 'Thing',
        'user_title': 'Mr',
        'password': '123456',
        'language': 'en',
        'policy_agreed': True
    }

AUTH_DATA = {
        'email': 'something@email.com',
        'password': '123456'
    }

class UserApiTest(ApiTestCase):

    def seed_static_data(self):
        self.add_organisation('Deep Learning Indaba')
        self.add_organisation('Deep Learning IndabaX')
        db.session.add(UserCategory('Postdoc'))
        db.session.add(Country('South Africa'))
        self.event1 = self.add_event({'en': 'Indaba'}, {'en': 'Indaba Event'},
                            datetime.now(), datetime.now(),
                            'SOUTHAFRI2019')
        self.event2 = self.add_event({'en': 'IndabaX'}, {'en': 'IndabaX Sudan'},
                            datetime.now(), datetime.now(),
                            'SUDANMO', 2)
        db.session.commit()

        self.event1_id = self.event1.id
        self.event2_id = self.event2.id

        self.add_email_template('verify-email')
        self.add_email_template('password-reset')

        db.session.flush()

    def get_auth_header_for(self, email):
        body = {
            'email': email,
            'password': 'abc'
        }
        response = self.app.post('api/v1/authenticate', data=body)
        data = json.loads(response.data)
        header = {'Authorization': data['token']}
        return header

    def test_registration(self):
        self.seed_static_data()
        response = self.app.post('/api/v1/user', data=USER_DATA)
        data = json.loads(response.data)

        assert data['id'] == 1
        assert len(data['token']) > 10

    def test_duplicate_registration(self):
        self.seed_static_data()
        response = self.app.post('/api/v1/user', data=USER_DATA)
        assert response.status_code == 201

        response = self.app.post('/api/v1/user', data=USER_DATA)
        assert response.status_code == 409

    def test_policy_not_agreed(self):
        self.seed_static_data()
        user_data = copy.deepcopy(USER_DATA)
        user_data['policy_agreed'] = False
        
        response = self.app.post('/api/v1/user', data=user_data)
        self.assertEqual(response.status_code, 400)

    def test_get_user(self):
        self.seed_static_data()
        response = self.app.post('/api/v1/user', data=USER_DATA)
        data = json.loads(response.data)

        headers = {'Authorization': data['token']}

        response = self.app.get('/api/v1/user', headers=headers)
        data = json.loads(response.data)
        assert data['email'] == 'something@email.com'
        assert data['firstname'] == 'Some'
        assert data['lastname'] == 'Thing'
        assert data['user_title'] == 'Mr'

    def test_update_user(self):
        self.seed_static_data()
        response = self.app.post('/api/v1/user', data=USER_DATA)
        data = json.loads(response.data)
        self.assertEqual(response.status_code, 201)

        headers = {'Authorization': data['token']}

        response = self.app.put('/api/v1/user', headers=headers, data={
            'email': 'something@email.com',
            'firstname': 'Updated',
            'lastname': 'Updated',
            'user_title': 'Mrs',
            'language': 'zu',
            'password': ''
        })

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.data)
        self.assertEqual(data['primary_language'], 'zu')

        response = self.app.get('/api/v1/user', headers=headers)
        data = json.loads(response.data)
        self.assertEqual(data['email'], 'something@email.com')
        self.assertEqual(data['firstname'], 'Updated')
        self.assertEqual(data['lastname'], 'Updated')
        self.assertEqual(data['user_title'], 'Mrs')

    def test_authentication_deleted(self):
        self.seed_static_data()
        response = self.app.post('/api/v1/user', data=USER_DATA)
        data = json.loads(response.data)
        assert response.status_code == 201

        headers = {'Authorization': data['token']}

        response = self.app.delete('api/v1/user', headers=headers)
        assert response.status_code == 200

        response = self.app.post('/api/v1/authenticate', data=AUTH_DATA)
        assert response.status_code == 404

    def test_authentication_unverified_email(self):
        self.seed_static_data()
        response = self.app.post('/api/v1/user', data=USER_DATA)
        assert response.status_code == 201

        response = self.app.post('/api/v1/authenticate', data=AUTH_DATA)
        assert response.status_code == 422

    def test_authentication_wrong_password(self):
        self.seed_static_data()
        response = self.app.post('/api/v1/user', data=USER_DATA)
        data = json.loads(response.data)
        assert response.status_code == 201

        user = db.session.query(AppUser).filter(
            AppUser.id == data['id']).first()

        response = self.app.get(
            '/api/v1/verify-email?token='+user.verify_token)
        assert response.status_code == 201

        response = self.app.post('/api/v1/authenticate', data={
            'email': 'something@email.com',
            'password': 'wrong'
        })
        assert response.status_code == 401

    def test_authentication(self):
        self.seed_static_data()
        response = self.app.post('/api/v1/user', data=USER_DATA)
        data = json.loads(response.data)
        assert response.status_code == 201

        user = db.session.query(AppUser).filter(
            AppUser.id == data['id']).first()

        response = self.app.get(
            '/api/v1/verify-email?token='+user.verify_token)
        assert response.status_code == 201

        response = self.app.post('/api/v1/authenticate', data=AUTH_DATA)
        assert response.status_code == 200

    def test_authentication_response(self):
        self.seed_static_data()
        response = self.app.post('/api/v1/user', data=USER_DATA)
        data = json.loads(response.data)

        user = db.session.query(AppUser).filter(
            AppUser.id == data['id']).first()

        response = self.app.get(
            '/api/v1/verify-email?token='+user.verify_token)

        role1 = EventRole('admin', data['id'], self.event1_id)
        role2 = EventRole('reviewer', data['id'], self.event2_id)

        db.session.add(role1)
        db.session.add(role2)
        db.session.commit()
        db.session.flush()

        response = self.app.post('/api/v1/authenticate', data=AUTH_DATA)
        data = json.loads(response.data)

        self.assertEqual(data['firstname'], USER_DATA['firstname'])
        self.assertEqual(data['lastname'], USER_DATA['lastname'])
        self.assertEqual(data['title'], USER_DATA['user_title'])
        self.assertEqual(data['roles'], [
            {'event_id': self.event1_id, 'role': 'admin'},
            {'event_id': self.event2_id, 'role': 'reviewer'},
        ])

    def test_password_reset_user_does_not_exist(self):
        response = self.app.post('/api/v1/password-reset/request', data={
            'email': 'something@email.com'
        })
        assert response.status_code == 404

    def test_password_reset_expired(self):
        self.seed_static_data()
        response = self.app.post('/api/v1/user', data=USER_DATA)
        data = json.loads(response.data)
        assert response.status_code == 201

        user = db.session.query(AppUser).filter(
            AppUser.id == data['id']).first()

        response = self.app.get(
            '/api/v1/verify-email?token='+user.verify_token)
        assert response.status_code == 201

        response = self.app.post('/api/v1/password-reset/request', data={
            'email': 'something@email.com'
        })
        assert response.status_code == 201

        pw_reset = db.session.query(PasswordReset).first()
        pw_reset.date = datetime.now() - timedelta(days=2)
        db.session.commit()

        response = self.app.post('/api/v1/password-reset/confirm', data={
            'code': pw_reset.code,
            'password': 'abc123'
        })
        assert response.status_code == 400

    def test_password_reset(self):
        self.seed_static_data()
        response = self.app.post('/api/v1/user', data=USER_DATA)
        data = json.loads(response.data)
        assert response.status_code == 201

        user = db.session.query(AppUser).filter(
            AppUser.id == data['id']).first()

        response = self.app.get(
            '/api/v1/verify-email?token='+user.verify_token)
        assert response.status_code == 201

        response = self.app.post('/api/v1/password-reset/request', data={
            'email': 'something@email.com'
        })
        assert response.status_code == 201

        pw_reset = db.session.query(PasswordReset).first()

        response = self.app.post('/api/v1/password-reset/confirm', data={
            'code': "bad code",
            'password': 'abc123'
        })
        assert response.status_code == 418

        response = self.app.post('/api/v1/password-reset/confirm', data={
            'code': pw_reset.code,
            'password': 'abc123'
        })
        assert response.status_code == 201

        response = self.app.post('/api/v1/authenticate', data={
            'email': 'something@email.com',
            'password': 'abc123'
        })

        assert response.status_code == 200

    def test_deletion(self):
        self.seed_static_data()
        response = self.app.post('/api/v1/user', data=USER_DATA)
        data = json.loads(response.data)

        user_id = data['id']
        headers = {'Authorization': data['token']}
        response = self.app.delete('/api/v1/user', headers=headers)
        assert response.status_code == 200

        user = db.session.query(AppUser).filter(AppUser.id == user_id).first()
        assert user.email == 'something@email.com'
        assert user.is_deleted == True

    def test_resend_verification_email(self):
        self.seed_static_data()
        self.app.post('/api/v1/user', data=USER_DATA)
        response = self.app.get(
            '/api/v1/resend-verification-email?email={}'.format(USER_DATA['email']))
        assert response.status_code == 201

    def test_resend_verification_email_no_user(self):
        self.seed_static_data()

        response = self.app.get(
            '/api/v1/resend-verification-email?email={}'.format('nonexistant@dummy.com'))
        assert response.status_code == 404

    def setup_verified_user(self):
        user = AppUser(email='something@email.com', firstname='Some', lastname='Thing', user_title='Mr',password= '123456', organisation_id=1)
        user.verify_token = 'existing token'
        user.verify()
        db.session.add(user)
        db.session.commit()


    def setup_responses(self):
        application_forms = [
            self.create_application_form(1, True, False),
            self.create_application_form(2, False, False)
        ]
        db.session.add_all(application_forms)

        candidate1 =   AppUser(email='c1@c.com', firstname='candidate',   lastname='1', user_title='Mr', password='abc', organisation_id=1)
        candidate2 =   AppUser(email='c2@c.com', firstname='candidate',   lastname='2', user_title='Ms', password='abc', organisation_id=1)
        candidate3 =   AppUser(email='c3@c.com', firstname='candidate',   lastname='3', user_title='Mr', password='abc', organisation_id=1)
        event_admin =  AppUser(email='ea@ea.com',firstname='event_admin', lastname='1', user_title='Ms', password='abc', organisation_id=1)
        users = [candidate1, candidate2, candidate3, event_admin]
        for user in users:
            user.verify()
        db.session.add_all(users)

        event_role = EventRole('admin', 4, 1)
        db.session.add(event_role)

        self.add_response(1, 1, is_submitted=True)
        self.add_response(1, 2, is_withdrawn=True)
        self.add_response(2, 3, is_submitted=True)

    def test_email_change_gets_new_token_and_is_unverified(self):
        self.seed_static_data()
        self.setup_verified_user()
        response = self.app.post('/api/v1/authenticate', data=AUTH_DATA)
        data = json.loads(response.data)
        headers = {'Authorization': data['token']}

        response = self.app.put('/api/v1/user', headers=headers, data={
            'email': 'somethingnew@email.com',
            'firstname': 'Some',
            'lastname': 'Thing',
            'user_title': 'Mr',
            'language': 'en',
            'password':''
        })

        self.assertEqual(response.status_code,  200)

        user = db.session.query(AppUser).get(1)

        self.assertEqual(user.email, 'somethingnew@email.com')
        self.assertEqual(user.firstname, 'Some')
        self.assertEqual(user.lastname, 'Thing')
        self.assertEqual(user.user_title, 'Mr')
        self.assertEqual(user.verified_email, False)
        self.assertNotEqual(user.verify_token, 'existing token')

    def test_user_profile_list(self):
        self.seed_static_data()
        self.setup_responses()
        header = self.get_auth_header_for('ea@ea.com')
        params = {'event_id': 1}

        response = self.app.get('/api/v1/userprofilelist', headers=header, data=params)

        data = json.loads(response.data)
        print(data)
        data = sorted(data, key=lambda k: k['user_id'])

        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['user_id'], 1)
        self.assertEqual(data[0]['is_submitted'], True)
        self.assertEqual(data[0]['is_withdrawn'], False)
        self.assertEqual(data[0]['withdrawn_timestamp'], None)

        self.assertEqual(data[1]['user_id'], 2)
        self.assertEqual(data[1]['is_submitted'], False)
        self.assertEqual(data[1]['submitted_timestamp'], None)
        self.assertEqual(data[1]['is_withdrawn'], True)

class UserCommentAPITest(ApiTestCase):

    def seed_static_data(self):
        self.add_organisation('Deep Learning Indaba', 'blah.png', 'blah_big.png')
        db.session.add(UserCategory('Postdoc'))
        db.session.add(Country('South Africa'))
        self.event1 = self.add_event({'en': 'Indaba'}, {'en': 'Indaba Event'},
                            datetime.now(), datetime.now(),
                            'NAGSOLVER')
        db.session.add(self.event1)
        db.session.commit()

        self.event1_id = self.event1.id
        
        self.add_email_template('verify-email')
        self.add_email_template('password-reset')

        user_data1 = USER_DATA.copy()
        response = self.app.post('/api/v1/user', data=user_data1)
        self.user1 = json.loads(response.data)

        user_data2 = USER_DATA.copy()
        user_data2['email'] = 'person2@person.com'
        user_data2['firstname'] = 'Person'
        user_data2['lastname'] = 'Two'
        response = self.app.post('/api/v1/user', data=user_data2)
        self.user2 = json.loads(response.data)

        user2 = db.session.query(AppUser).filter(AppUser.email == 'person2@person.com').first()
        user2.is_admin = True

        db.session.flush()


    def seed_comments(self):
        self.comment1 = UserComment(self.event1_id, self.user1['id'], self.user2['id'], datetime.now(), 'Comment 1')
        self.comment2 = UserComment(self.event1_id, self.user1['id'], self.user2['id'], datetime.now(), 'Comment 2')
        self.comment3 = UserComment(self.event1_id, self.user2['id'], self.user1['id'], datetime.now(), 'Comment 3')

        db.session.add_all([self.comment1, self.comment2, self.comment3])
        db.session.flush()

    def test_post_comment(self):
        with app.app_context():
            self.seed_static_data()

            params = {'event_id': self.event1_id, 'user_id': self.user2['id'], 'comment': 'Comment1'}
            print('Sending params: ', params)
            response = self.app.post('/api/v1/user-comment', headers={'Authorization': self.user1['token']}, data=json.dumps(params), content_type='application/json')
            data = json.loads(response.data)

            self.assertEqual(response.status_code, 201)

    def test_get_forbidden(self):
        with app.app_context():
            self.seed_static_data()
            self.seed_comments()

            params = {'event_id': self.event1_id, 'user_id': self.user2['id']}
            response = self.app.get('/api/v1/user-comment', headers={'Authorization': self.user1['token']}, query_string=params)

            self.assertEqual(response.status_code, 403)

    def test_get_comments(self):
        with app.app_context():
            self.seed_static_data()
            self.seed_comments()

            params = {'event_id': self.event1_id, 'user_id': self.user1['id']}
            response = self.app.get('/api/v1/user-comment', headers={'Authorization': self.user2['token']}, query_string=params)
            comment_list = json.loads(response.data)

            self.assertEqual(len(comment_list), 2)
            self.assertEqual(comment_list[0]['event_id'], self.comment1.event_id)
            self.assertEqual(comment_list[0]['user_id'], self.comment1.user_id)
            self.assertEqual(comment_list[0]['comment_by_user_firstname'], self.user2['firstname'])
            self.assertEqual(comment_list[0]['comment_by_user_lastname'], self.user2['lastname'])
            self.assertEqual(comment_list[0]['comment'], self.comment1.comment)

            self.assertEqual(comment_list[1]['event_id'], self.comment2.event_id)
            self.assertEqual(comment_list[1]['user_id'], self.comment2.user_id)
            self.assertEqual(comment_list[1]['comment_by_user_firstname'], self.user2['firstname'])
            self.assertEqual(comment_list[1]['comment_by_user_lastname'], self.user2['lastname'])
            self.assertEqual(comment_list[1]['comment'], self.comment2.comment)

class UserProfileApiTest(ApiTestCase):
    def setup_static_data(self):
        self.add_organisation('Deep Learning Indaba', 'blah.png', 'blah_big.png')
        self.add_organisation('Deep Learning IndabaX', 'blah.png', 'blah_big.png')
        db.session.add(UserCategory('Postdoc'))
        db.session.add(Country('South Africa'))
        db.session.commit()

        events = [
            self.add_event({'en': 'Indaba'}, {'en': 'Indaba Event'}, datetime.now(), datetime.now(), 'ADAMOPTIM'),
            self.add_event({'en': 'Indaba2'}, {'en': 'Indaba Event 2'}, datetime.now(), datetime.now(), 'HACFTET', 2)
        ]

        application_forms = [
            self.create_application_form(1, True, False),
            self.create_application_form(2, False, False)
        ]
        db.session.add_all(application_forms)

        candidate1 = AppUser(email='c1@c.com', firstname='candidate', lastname='1', user_title='Mr',password= 'abc', organisation_id=1)
        candidate2 = AppUser(email='c2@c.com', firstname='candidate', lastname='2', user_title='Ms', password='abc', organisation_id=1)
        system_admin = AppUser(email='system_admin@sa.com', firstname='system_admin', lastname='1', user_title='Mr',password='abc', organisation_id=1, is_admin=True)
        event_admin = AppUser(email='event_admin@ea.com', firstname='event_admin', lastname='1', user_title='Ms', password='abc',organisation_id=1)
        reviewer = AppUser(email='reviewer@r.com', firstname='reviewer', lastname='1', user_title='Ms', password='abc', organisation_id=1)
        users = [candidate1, candidate2, system_admin, event_admin, reviewer]
        for user in users:
            user.verify()
        db.session.add_all(users)

        event_roles = [
            EventRole('admin', 4, 1),
            EventRole('reviwer', 5, 1)
        ]
        db.session.add_all(event_roles)
        db.session.commit()
        self.add_response(1, 1, is_submitted=True)
        self.add_response(2, 2, is_submitted=True)
    
    def get_auth_header_for(self, email):
        body = {
            'email': email,
            'password': 'abc'
        }
        response = self.app.post('api/v1/authenticate', data=body)
        data = json.loads(response.data)
        header = {'Authorization': data['token']}
        return header

    def test_user_not_found_when_not_event_admin(self):
        self.setup_static_data()
        header = self.get_auth_header_for('reviewer@r.com')
        params = {'user_id': 1}

        response = self.app.get('/api/v1/userprofile', headers=header, data=params)

        self.assertEqual(response.status_code, 404)
    
    def test_user_not_found_when_does_not_exist(self):
        self.setup_static_data()
        header = self.get_auth_header_for('system_admin@sa.com')
        params = {'user_id': 99}

        response = self.app.get('/api/v1/userprofile', headers=header, data=params)

        self.assertEqual(response.status_code, 404)

    def test_get_user_when_system_admin(self):
        self.setup_static_data()
        header = self.get_auth_header_for('system_admin@sa.com')
        params = {'user_id': 2}

        response = self.app.get('/api/v1/userprofile', headers=header, data=params)

        data = json.loads(response.data)
        self.assertEqual(data['email'], 'c2@c.com')

    def test_get_user_when_event_admin(self):
        self.setup_static_data()
        header = self.get_auth_header_for('event_admin@ea.com')
        params = {'user_id': 1}

        response = self.app.get('/api/v1/userprofile', headers=header, data=params)

        data = json.loads(response.data)
        self.assertEqual(data['email'], 'c1@c.com')

class EmailerAPITest(ApiTestCase):
    def setup_static_data(self):
        db.session.add(UserCategory('Postdoc'))
        db.session.add(Country('South Africa'))

        self.candidate1 =   AppUser(email='c1@c.com', firstname='candidate',   lastname='1', user_title='Mr', password='abc', organisation_id=1)
        self.candidate2 =   AppUser(email='c2@c.com', firstname='candidate',   lastname='2', user_title='Ms', password='abc', organisation_id=1)
        self.system_admin = AppUser(email='system_admin@sa.com', firstname='system_admin', lastname='1', user_title='Mr', password='abc', organisation_id=1,is_admin=True)

        users = [self.candidate1, self.candidate2, self.system_admin]
        for user in users:
            user.verify()
        db.session.add_all(users)

        db.session.commit()
    
    def get_auth_header_for(self, email):
        body = {
            'email': email,
            'password': 'abc'
        }
        response = self.app.post('api/v1/authenticate', data=body)
        data = json.loads(response.data)
        header = {'Authorization': data['token']}
        return header

    def test_forbidden_when_not_admin(self):
        with app.app_context():
            self.setup_static_data()
            header = self.get_auth_header_for('c1@c.com')
            params = {
                'user_id': self.candidate2.id,
                'email_subject': 'This is a test email',
                'email_body': 'Hello world, this is a test email.'
            }

            response = self.app.post('/api/v1/admin/emailer', headers=header, data=params)

            self.assertEqual(response.status_code, 403)
    
    def test_email(self):
        with app.app_context():
            self.setup_static_data()
            header = self.get_auth_header_for('system_admin@sa.com')
            params = {
                'user_id': self.candidate2.id,
                'email_subject': 'This is a test email',
                'email_body': 'Hello world, this is a test email.'
            }

            response = self.app.post('/api/v1/admin/emailer', headers=header, data=params)
            self.assertEqual(response.status_code, 200)

class OrganisationUserTest(ApiTestCase):
    """Test that users are correctly linked to organisations"""
    def seed_static_data(self):
        db.session.add(UserCategory('Postdoc'))
        db.session.add(Country('South Africa'))
        self.add_organisation('Deep Learning Indaba', 'blah.png', 'blah_big.png', domain='indaba')

        self.user1_org1 = AppUser('first_user@c.com', 'candidate', '1', 'Mr',  password="abc",organisation_id=1)
        self.user1_org2 = AppUser('first_user@c.com', 'candidate', '2', 'Ms',  password="abc",organisation_id=2)
        self.user2_org1 = AppUser('second_user@c.com', 'system_admin', '1', 'Mr', password="abc",organisation_id=1, is_admin=True)

        users = [self.user1_org1, self.user1_org2, self.user2_org1]
        for user in users:
            user.verify()
        db.session.add_all(users)

        self.add_email_template('verify-email')
        self.add_email_template('password-reset')

        db.session.commit()

    def get_auth_header_for(self, email, domain):
        body = {
            'email': email,
            'password': 'abc'
        }

        response = self.app.post('api/v1/authenticate', data=body, headers={'Origin': domain})
        data = json.loads(response.data)

        header = {
            'Authorization': data['token'],
            'Origin': domain
        }
        return header

    def test_auth_org(self):
        """Test that authentication is linked to organisation."""
        with app.app_context():
            self.seed_static_data()
            headers = self.get_auth_header_for('first_user@c.com', 'www.indaba.net/blah')
            response = self.app.get('/api/v1/user', headers=headers)
            data = json.loads(response.data)
            self.assertEqual(data['firstname'], 'candidate')
            self.assertEqual(data['lastname'], '2')

            headers = self.get_auth_header_for('first_user@c.com', 'www.org.net/blah')
            response = self.app.get('/api/v1/user', headers=headers)
            data = json.loads(response.data)
            self.assertEqual(data['firstname'], 'candidate')
            self.assertEqual(data['lastname'], '1')

    def test_cant_auth_outside_org(self):
        with app.app_context():
            self.seed_static_data()
            body = {
                'email': 'second_user@c.com',
                'password': 'abc'
            }

            response = self.app.post('api/v1/authenticate', data=body, headers={'Origin': 'www.indaba.net/blah'})
            self.assertEqual(response.status_code, 401)

    def allow_same_email_different_org(self):
        db.session.add(UserCategory('Postdoc'))
        db.session.add(Country('South Africa'))
        self.add_organisation('Deep Learning Indaba', 'blah.png', 'blah_big.png')

        response = self.app.post('/api/v1/user', data=USER_DATA, headers={'Origin': 'www.myorg.net'})
        self.assertEqual(response.status_code, 201)

        response = self.app.post('/api/v1/user', data=USER_DATA, headers={'Origin': 'www.indaba.net'})
        self.assertEqual(response.status_code, 201)

        response = self.app.post('/api/v1/user', data=USER_DATA, headers={'Origin': 'www.indaba.net'})
        self.assertEqual(response.status_code, 409)


class PrivacyPolicyApiTest(ApiTestCase):

    def test_policy_agreed(self):
        user = self.add_user()
        user.policy_agreed_datetime = None
        db.session.commit()

        headers = self.get_auth_header_for('user@user.com')
        response = self.app.put('/api/v1/privacypolicy', headers=headers, data={'policy_agreed': True})

        self.assertEqual(response.status_code, 200)

    def test_policy_already_agreed(self):
        user = self.add_user()

        headers = self.get_auth_header_for('user@user.com')
        response = self.app.put('/api/v1/privacypolicy', headers=headers, data={'policy_agreed': True})

        data = json.loads(response.data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(data['message'], POLICY_ALREADY_AGREED[0]['message'])
    
    def test_policy_not_agreed(self):
        user = self.add_user()

        headers = self.get_auth_header_for('user@user.com')
        response = self.app.put('/api/v1/privacypolicy', headers=headers, data={'policy_agreed': False})

        data = json.loads(response.data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(data['message'], POLICY_NOT_AGREED[0]['message'])


class EventAttendeeAPITest(ApiTestCase):
    def seed_static_data(self):
        self.event = self.add_event()
        self.user1 = self.add_user()
        self.app_form = self.create_application_form()
        self.response = self.add_response(self.app_form.id, self.user1.id, True, False)

        self.add_email_template('verify-email')
        self.add_email_template('password-reset')
    
    def test_auth_required(self):
        """Check that response is 401 when no auth token provided."""
        self.seed_static_data()
        response = self.app.post('/api/v1/validate-user-event-attendee', data={'event_id': 1})
        self.assertEqual(response.status_code, 401)

    def test_non_attendee(self):
        """Check that response is 401 when user is not an attendee."""
        self.seed_static_data()
        response = self.app.post(
            '/api/v1/validate-user-event-attendee',
            headers=self.get_auth_header_for(self.user1.email),
            data={'event_id': 1}
        )
        self.assertEqual(response.status_code, 401)

    def test_non_attendee_with_offer(self):
        """Check that response is 401 when user hasn't responded or rejected their offer."""
        self.seed_static_data()
        offer = self.add_offer(self.user1.id)
        response = self.app.post(
            '/api/v1/validate-user-event-attendee',
            headers=self.get_auth_header_for(self.user1.email), 
            data={'event_id': 1}
        )
        self.assertEqual(response.status_code, 401)

        offer.candidate_response = False
        db.session.commit()
        response = self.app.post(
            '/api/v1/validate-user-event-attendee',
            headers=self.get_auth_header_for(self.user1.email),
            data={'event_id': 1}
        )
        self.assertEqual(response.status_code, 401)

    def test_attendee_offer(self):
        """Check that response is 200 when user has accepted an offer."""
        self.seed_static_data()
        offer = self.add_offer(self.user1.id)
        offer.candidate_response = True
        db.session.commit()

        response = self.app.post(
            '/api/v1/validate-user-event-attendee',
            headers=self.get_auth_header_for(self.user1.email), 
            data={'event_id': 1}
        )
        self.assertEqual(response.status_code, 200)

    def test_invited_guest(self):
        """Check that response is 200 when user is an invited guest."""
        self.seed_static_data()
        self.add_invited_guest(self.user1.id)
        response = self.app.post(
            '/api/v1/validate-user-event-attendee',
            headers=self.get_auth_header_for(self.user1.email), 
            data={'event_id': 1}
        )
        self.assertEqual(response.status_code, 200)
