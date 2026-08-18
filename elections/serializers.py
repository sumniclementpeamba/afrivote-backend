import csv
import io
import PyPDF2
import docx
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Election, Position, Candidate, Voter, Vote

User = get_user_model()


# ─── Text extraction helpers ──────────────────────────────────────────────────
def extract_text_from_pdf(file):
    reader = PyPDF2.PdfReader(file)
    text = ""
    for page in reader.pages:
        text += page.extract_text() or ""
    return text

def extract_text_from_docx(file):
    doc = docx.Document(file)
    return "\n".join([para.text for para in doc.paragraphs])

def extract_text(file):
    if file.name.endswith('.pdf'):
        return extract_text_from_pdf(file)
    elif file.name.endswith('.docx'):
        return extract_text_from_docx(file)
    else:
        raise serializers.ValidationError("Unsupported file format. Only PDF and DOCX are allowed.")


# ─── Election Serializer ──────────────────────────────────────────────────────
class ElectionSerializer(serializers.ModelSerializer):
    organization_name = serializers.SerializerMethodField()
    total_votes = serializers.SerializerMethodField()
    is_active = serializers.ReadOnlyField()

    class Meta:
        model = Election
        fields = [
            'id', 'organization', 'organization_name', 'title', 'description',
            'election_type', 'start_date', 'end_date', 'status',
            'is_anonymous', 'allow_write_ins', 'require_voter_verification',
            'show_results_during_election', 'show_results_after_election',
            'eligible_voter_count', 'total_votes', 'is_active',
            'is_paid_voting',                # NEW
            'vote_price',                    # NEW
            'slug',                          # NEW
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'organization', 'created_at', 'updated_at', 'is_active', 'slug']

    def get_organization_name(self, obj):
        return obj.organization.name if obj.organization else None

    def get_total_votes(self, obj):
        return Vote.objects.filter(election=obj).count()

    def validate(self, data):
        start = data.get('start_date')
        end = data.get('end_date')
        if start and end and end <= start:
            raise serializers.ValidationError({"end_date": "End date must be after start date."})
        return data


# ─── Position Serializer ──────────────────────────────────────────────────────
class PositionSerializer(serializers.ModelSerializer):
    candidate_count = serializers.SerializerMethodField()

    class Meta:
        model = Position
        fields = [
            'id', 'election', 'title', 'description',
            'max_selections', 'order', 'is_required',
            'display_order', 'candidate_count',
        ]
        read_only_fields = ['id']

    def get_candidate_count(self, obj):
        return obj.candidates.count()


# ─── Candidate Serializer ─────────────────────────────────────────────────────
class CandidateSerializer(serializers.ModelSerializer):
    vote_count = serializers.SerializerMethodField()
    vote_percentage = serializers.SerializerMethodField()
    photo_url = serializers.SerializerMethodField(read_only=True)   # new output field
    position_title = serializers.CharField(source='position.title', read_only=True)
    election_title = serializers.SerializerMethodField(read_only=True)
    biography_upload = serializers.FileField(write_only=True, required=False)
    manifesto_upload = serializers.FileField(write_only=True, required=False)

    class Meta:
        model = Candidate
        fields = [
            'id', 'position', 'position_title', 'election_title',
            'name', 'biography', 'photo', 'photo_url', 'manifesto', 'email', 'phone',
            'department', 'is_approved', 'is_active',
            'vote_count', 'vote_percentage',
            'created_at', 'order', 'biography_upload', 'manifesto_upload',
        ]
        read_only_fields = ['id', 'created_at', 'position_title', 'election_title', 'photo_url']

    def get_vote_count(self, obj):
        return Vote.objects.filter(candidate=obj).count()

    def get_vote_percentage(self, obj):
        total = Vote.objects.filter(position=obj.position).count()
        if total == 0:
            return 0
        return round((self.get_vote_count(obj) / total) * 100, 2)

    def get_photo_url(self, obj):
        if obj.photo:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.photo.url)
            return obj.photo.url
        return None

    def get_election_title(self, obj):
        if obj.position and obj.position.election:
            return obj.position.election.title
        return None

    def create(self, validated_data):
        bio_file = validated_data.pop('biography_upload', None)
        manifesto_file = validated_data.pop('manifesto_upload', None)

        if bio_file:
            validated_data['biography'] = extract_text(bio_file)
        if manifesto_file:
            validated_data['manifesto'] = extract_text(manifesto_file)

        validated_data['is_active'] = True
        validated_data['is_approved'] = True

        return super().create(validated_data)

    def update(self, instance, validated_data):
        bio_file = validated_data.pop('biography_upload', None)
        manifesto_file = validated_data.pop('manifesto_upload', None)

        if bio_file:
            instance.biography = extract_text(bio_file)
        if manifesto_file:
            instance.manifesto = extract_text(manifesto_file)

        return super().update(instance, validated_data)


# ─── Voter Serializer ─────────────────────────────────────────────────────────
class VoterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Voter
        fields = '__all__'


# ─── Vote Serializer ──────────────────────────────────────────────────────────
class VoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Vote
        fields = ['id', 'election', 'position', 'candidate', 'voted_at']
        read_only_fields = ['id', 'election', 'voted_at']


# ─── CSV Upload Serializer ────────────────────────────────────────────────────
class VoterCSVUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

    def create(self, validated_data):
        file = validated_data['file']
        decoded_file = file.read().decode('utf-8')
        reader = csv.DictReader(io.StringIO(decoded_file))
        created_count = 0
        errors = []
        default_password = 'Vote@123'

        organization = self.context['organization']

        for row in reader:
            email = row.get('email', '').strip()
            first_name = row.get('first_name', '').strip()
            last_name = row.get('last_name', '').strip()
            voter_id = row.get('voter_id', '').strip()

            if not email or not first_name or not last_name:
                errors.append(f"Missing required fields in row: {row}")
                continue

            user, user_created = User.objects.get_or_create(
                email=email,
                defaults={
                    'first_name': first_name,
                    'last_name': last_name,
                    'organization': organization,
                    'role': 'VOTER',
                    'is_verified': True,
                }
            )

            # Force voter role and organisation
            user.role = 'VOTER'
            user.organization = organization
            user.is_verified = True

            if user_created:
                user.set_password(default_password)

            user.save()

            voter, voter_created = Voter.objects.get_or_create(
                user=user,
                organization=organization,
                defaults={
                    'email': email,
                    'first_name': first_name,
                    'last_name': last_name,
                    'voter_id': voter_id or f"V{user.id}",
                    'is_verified': True,
                }
            )
            if not voter_created:
                voter.email = email
                voter.first_name = first_name
                voter.last_name = last_name
                if not voter.voter_id:
                    voter.voter_id = voter_id or f"V{user.id}"
                voter.is_verified = True
                voter.save()

            created_count += 1

        return {
            'created': created_count,
            'errors': errors,
        }


# ─── Voter Invitation Serializer ──────────────────────────────────────────────
class VoterInvitationSerializer(serializers.Serializer):
    voter_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True
    )
    send_all = serializers.BooleanField(default=False)

    def validate(self, data):
        if not data.get('send_all') and not data.get('voter_ids'):
            raise serializers.ValidationError("Either 'voter_ids' or 'send_all' must be provided.")
        return data