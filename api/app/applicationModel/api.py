from datetime import datetime
import traceback

import flask_restful as restful

from flask_restful import reqparse, fields, marshal_with, marshal
from sqlalchemy.exc import SQLAlchemyError
from flask import g

from app.applicationModel.models import ApplicationForm, Question, Section
from app.applicationModel.repository import ApplicationFormRepository as app_repository
from app.users.repository import UserRepository as user_repository
from app.events.models import Event

from app.utils.auth import auth_required

from app.utils.errors import EVENT_NOT_FOUND, FORM_NOT_FOUND_BY_ID, APPLICATION_FORM_EXISTS, QUESTION_NOT_FOUND, \
    SECTION_NOT_FOUND, DB_NOT_AVAILABLE, FORM_NOT_FOUND, APPLICATIONS_CLOSED, FORBIDDEN, UPDATE_CONFLICT

from app import db, bcrypt
from app import LOGGER


class ApplicationFormAPI(restful.Resource):
    question_fields = {
        'id': fields.Integer,
        'type': fields.String,
        'description': fields.String,
        'headline': fields.String,
        'order': fields.Integer,
        'options': fields.Raw,
        'placeholder': fields.String,
        'validation_regex': fields.String,
        'validation_text': fields.String,
        'is_required': fields.Boolean,
        'depends_on_question_id': fields.Integer,
        'show_for_values': fields.Raw,
        'key': fields.String
    }

    section_fields = {
        'id': fields.Integer,
        'name': fields.String,
        'description': fields.String,
        'order': fields.Integer,
        'questions': fields.List(fields.Nested(question_fields)),
        'depends_on_question_id': fields.Integer,
        'show_for_values': fields.Raw,
        'key': fields.String
    }

    form_fields = {
        'id': fields.Integer,
        'event_id': fields.Integer,
        'is_open': fields.Boolean,
        'deadline': fields.DateTime,
        'sections': fields.List(fields.Nested(section_fields)),
        'nominations': fields.Boolean
    }

    def get(self):
        req_parser = reqparse.RequestParser()
        req_parser.add_argument('event_id', type=int, required=True,
                                help='Invalid event_id requested. Event_id\'s should be of type int.')

        LOGGER.debug('Received get request for application form')
        args = req_parser.parse_args()
        LOGGER.debug('Parsed Args for event_id: {}'.format(args))

        try:
            form = db.session.query(ApplicationForm).filter(ApplicationForm.event_id == args['event_id']).first()
            if (not form):
                LOGGER.warn('Form not found for event_id: {}'.format(args['event_id']))
                return FORM_NOT_FOUND

            if not form.is_open:
                return APPLICATIONS_CLOSED

            if (form):
                return marshal(form, self.form_fields)
            else:
                LOGGER.warn("Event not found for event_id: {}".format(args['event_id']))
                return EVENT_NOT_FOUND

        except SQLAlchemyError as e:
            LOGGER.error("Database error encountered: {}".format(e))
            return DB_NOT_AVAILABLE
        except:
            LOGGER.error("Encountered unknown error: {}".format(traceback.format_exc()))
            return DB_NOT_AVAILABLE

    @auth_required
    @marshal_with(form_fields)
    def post(self):
        req_parser = reqparse.RequestParser()
        req_parser.add_argument('event_id', type=int, required=True,
                                help='Invalid event_id requested. Event_id\'s should be of type int.')
        req_parser.add_argument('is_open', type=bool, required=True)
        req_parser.add_argument('nominations', type=bool, required=True)
        req_parser.add_argument('sections', type=dict, required=True, action='append')
        args = req_parser.parse_args()
        event_id = args['event_id']

        event = db.session.query(Event).get(event_id)
        if not event:
            return EVENT_NOT_FOUND

        user_id = g.current_user["id"]
        current_user = user_repository.get_by_id(user_id)
        if not current_user.is_event_admin(event_id):
            return FORBIDDEN

        app_form = app_repository.get_by_event_id(event_id)
        if app_form:
            return APPLICATION_FORM_EXISTS
        else:
            is_open = args['is_open']
            nominations = args['nominations']

            app_form = ApplicationForm(
                event_id,
                is_open,
                nominations
            )
            db.session.add(app_form)
            db.session.commit()
        section_args = args['sections']

        for s in section_args:
            section = Section(
                app_form.id,
                s['name'],
                s['description'],
                s['order']
            )
            db.session.add(section)
            db.session.commit()

            for q in s['questions']:
                question = Question(
                    app_form.id,
                    section.id,
                    q['headline'],
                    q['placeholder'],
                    q['order'],
                    q['type'],
                    q['validation_regex'],
                    q['validation_text'],
                    q['is_required'],
                    q['description'],
                    q['options'],
                )
                db.session.add(question)
                db.session.commit()
        app_form = app_repository.get_by_id(app_form.id)
        return app_form, 201

    @auth_required
    @marshal_with(form_fields)
    def put(self):
        req_parser = reqparse.RequestParser()
        req_parser.add_argument('event_id', type=int, required=True,
                                help='Invalid event_id requested. Event_id\'s should be of type int.')
        req_parser.add_argument('is_open', type=bool, required=True)
        req_parser.add_argument('nominations', type=bool, required=True)
        req_parser.add_argument('id', type=int, required=True)
        req_parser.add_argument('sections', type=dict, required=True, action='append')

        args = req_parser.parse_args()
        event_id = args['event_id']
        user_id = g.current_user['id']
        app_id = args['id']

        event = db.session.query(Event).get(event_id)
        if not event:
            return EVENT_NOT_FOUND

        current_user = user_repository.get_by_id(user_id)
        if not current_user.is_event_admin(event_id):
            return FORBIDDEN

        app_form = app_repository.get_by_id(app_id)
        if not app_repository.get_by_id(app_id):
            return FORM_NOT_FOUND_BY_ID

        if not event_id == app_form.event_id:
            return UPDATE_CONFLICT

        app_form.is_open = args['is_open']
        app_form.nominations = args['nominations']

        current_sections = app_form.sections
        new_sections = args['sections']
        for new_s in new_sections:
            if 'id' in new_s:
                # If ID is populated, then compare to the new section and update
                for current_s in current_sections:
                    if current_s.id == new_s['id']:
                        current_s.description = new_s['description']
                        current_s.order = new_s['order']
                        # current_s.depends_on_question_id = new_s['depends_on_question_id']
                        current_s.show_for_values = new_s['show_for_values']
                        current_s.key = new_s['key']
                        current_s.name = new_s['name']

                        for new_q in new_s['questions']:  # new_q - questions from new_s section
                            if 'id' in new_q:
                                for idx in current_s.questions:
                                    if idx.id == new_q['id']:
                                        idx.headline = new_q['headline']
                                        idx.placeholder = new_q['placeholder']
                                        idx.order = new_q['order']
                                        idx.type = new_q['type']
                                        idx.validation_regex = new_q['validation_regex']
                                        idx.validation_text = new_q['validation_text']
                                        idx.is_required = new_q['is_required']
                                        idx.description = new_q['description']
                                        idx.options = new_q['options']
                            else:
                                new_question = Question(
                                    app_form.id,
                                    current_s.id,
                                    new_q['headline'],
                                    new_q['placeholder'],
                                    new_q['order'],
                                    new_q['type'],
                                    new_q['validation_regex'],
                                    new_q['validation_text'],
                                    new_q['is_required'],
                                    new_q['description'],
                                    new_q['options']
                                )
                                db.session.add(new_question)
                                db.session.commit()

            else:
                # if not populated, then add new section
                section = Section(
                    app_form.id,
                    new_s['name'],
                    new_s['description'],
                    new_s['order']
                )
                db.session.add(section)
                db.session.commit()
                for q in new_s['questions']:
                    question = Question(
                        app_form.id,
                        section.id,
                        q['headline'],
                        q['placeholder'],
                        q['order'],
                        q['type'],
                        q['validation_regex'],
                        q['validation_text'],
                        q['is_required'],
                        q['description'],
                        q['options']
                    )
                    db.session.add(question)
                    db.session.commit()

        for c in current_sections:
            match = False
            for new in new_sections:
                if 'id' in new:
                    if c.id == new['id']:
                        match = True
            if not match:
                app_repository.delete_section_by_id(c.id)

        db.session.commit()

        return app_form, 200
