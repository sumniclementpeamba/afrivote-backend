import csv
from datetime import timedelta
from collections import defaultdict

from django.db.migrations import serializer
import requests
from rest_framework import viewsets, status, serializers
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.utils import timezone
from django.http import HttpResponse
from reportlab.lib.pagesizes import A4
from django.core.mail import send_mail
from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.units import inch
from reportlab.graphics.shapes import Drawing, Rect, String, Line

from organizations.models import Organization
from organizations.permissions import IsNotVoter, IsOrgAdmin, IsSuperAdmin
from .models import Election, ElectionShareLink, Position, Candidate, Voter, Vote, VoterRecord
from .serializers import (
    ElectionSerializer,
    PositionSerializer,
    CandidateSerializer,
    VoterSerializer,
    VoteSerializer,
    VoterCSVUploadSerializer,
    VoterInvitationSerializer,
)
from .authentication import QueryParamJWTAuthentication
from audit.utils import log_audit


# ─── Helper: Generate PDF Results ──────────────────────────────────────────────
def generate_election_results_pdf(election, request=None, disposition='attachment'):
    org = election.organization
    eligible_voters = Voter.objects.filter(organization=org, is_active=True, is_verified=True).count()
    total_votes_cast = VoterRecord.objects.filter(election=election).values('voter').distinct().count()
    remaining = eligible_voters - total_votes_cast
    turnout_percent = (total_votes_cast / eligible_voters * 100) if eligible_voters > 0 else 0

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'{disposition}; filename="{election.title}_results.pdf"'

    doc = SimpleDocTemplate(response, pagesize=A4, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=18)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'], fontSize=18, spaceAfter=12, textColor=colors.HexColor('#1e3a8a'))
    subtitle_style = ParagraphStyle('SubTitle', parent=styles['Normal'], fontSize=11, spaceAfter=6, textColor=colors.gray)
    normal = styles['Normal']

    elements = []
    elements.append(Paragraph(f"Election Results: {election.title}", title_style))
    elements.append(Paragraph(f"Status: {election.status}  |  Date: {election.start_date.strftime('%Y-%m-%d %H:%M')}", subtitle_style))
    elements.append(Spacer(1, 12))

    turnout_data = [
        ['Voter Turnout', ''],
        ['Eligible Voters', str(eligible_voters)],
        ['Votes Cast', str(total_votes_cast)],
        ['Remaining', str(remaining)],
        ['Turnout', f'{turnout_percent:.1f}%'],
    ]
    turnout_table = Table(turnout_data, colWidths=[2.5*inch, 1.5*inch])
    turnout_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e0e7ff')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#1e3a8a')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(turnout_table)
    elements.append(Spacer(1, 16))

    chart_colors = [
        colors.HexColor('#6366f1'), colors.HexColor('#8b5cf6'), colors.HexColor('#d946ef'),
        colors.HexColor('#f59e0b'), colors.HexColor('#14b8a6'),
    ]

    positions = election.positions.all()
    for position in positions:
        pos_total = Vote.objects.filter(election=election, position=position).count()
        elements.append(Paragraph(f"Position: {position.title}", styles['Heading2']))
        elements.append(Paragraph(f"Total votes: {pos_total}", normal))
        candidates = position.candidates.all()
        if candidates:
            cand_data = [['Candidate', 'Votes', 'Percentage']]
            for cand in candidates:
                vote_count = Vote.objects.filter(election=election, position=position, candidate=cand).count()
                perc = (vote_count / pos_total * 100) if pos_total > 0 else 0
                cand_data.append([cand.name, str(vote_count), f"{perc:.1f}%"])
            cand_table = Table(cand_data, colWidths=[2.5*inch, 1.2*inch, 1.2*inch])
            cand_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f3f4f6')),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('ALIGN', (1, 1), (-1, -1), 'CENTER'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ]))
            elements.append(cand_table)
            elements.append(Spacer(1, 10))

            if pos_total > 0:
                elements.append(Paragraph("Vote Distribution", styles['Heading3']))
                chart_data = []
                for cand in candidates:
                    vc = Vote.objects.filter(election=election, position=position, candidate=cand).count()
                    perc = (vc / pos_total * 100) if pos_total > 0 else 0
                    chart_data.append((cand.name, vc, perc))
                chart_data.sort(key=lambda x: x[1], reverse=True)

                chart_width, chart_height = 450, 220
                bar_area_bottom, bar_area_top = 40, chart_height - 30
                bar_area_left, bar_area_right = 50, chart_width - 10
                bar_area_width = bar_area_right - bar_area_left
                max_votes = max(v[1] for v in chart_data) if chart_data else 1

                drawing = Drawing(chart_width, chart_height)
                num_ticks = 5
                tick_interval = max_votes / num_ticks if max_votes > 0 else 1
                for i in range(num_ticks + 1):
                    y = bar_area_bottom + (i * (bar_area_top - bar_area_bottom) / num_ticks)
                    value = int(i * tick_interval)
                    drawing.add(Line(bar_area_left, y, bar_area_right, y, strokeColor=colors.HexColor('#e2e8f0'), strokeWidth=0.5))
                    drawing.add(String(bar_area_left - 45, y - 5, str(value), fontSize=8, fillColor=colors.gray))

                num_candidates = len(chart_data)
                bar_width = bar_area_width / num_candidates * 0.7
                gap = (bar_area_width / num_candidates) - bar_width

                for i, (name, votes, perc) in enumerate(chart_data):
                    x = bar_area_left + i * (bar_width + gap) + gap / 2
                    bar_height = (votes / max_votes) * (bar_area_top - bar_area_bottom) if max_votes > 0 else 0
                    y = bar_area_bottom
                    color = chart_colors[i % len(chart_colors)]
                    drawing.add(Rect(x, y, bar_width, bar_height, fillColor=color, strokeColor=color))
                    label = f"{votes} ({perc:.1f}%)"
                    drawing.add(String(x + bar_width/2, y + bar_height + 3, label, fontSize=7, fillColor=colors.HexColor('#334155'), textAnchor='middle'))
                    short_name = name[:12] + ('...' if len(name) > 12 else '')
                    drawing.add(String(x + bar_width/2, bar_area_bottom - 12, short_name, fontSize=7, fillColor=colors.HexColor('#475569'), textAnchor='middle'))
                elements.append(drawing)
                elements.append(Spacer(1, 10))
        else:
            elements.append(Paragraph("No candidates", normal))
        elements.append(Spacer(1, 10))

    doc.build(elements)
    return response


# ─── Helper: Get results data ──────────────────────────────────────────────────
def get_election_results(election, request=None):
    organization = election.organization
    eligible_voters = Voter.objects.filter(
        organization=organization, is_active=True, is_verified=True
    ).count()
    total_votes_cast = VoterRecord.objects.filter(election=election).values('voter').distinct().count()
    results_data = {
        'election_id': str(election.id),
        'election_title': election.title,
        'status': election.status,
        'eligible_voters': eligible_voters,
        'total_votes_cast': total_votes_cast,
        'positions': []
    }
    positions = election.positions.all()
    for position in positions:
        total_votes_for_position = Vote.objects.filter(election=election, position=position).count()
        position_info = {
            'position_id': str(position.id),
            'title': position.title,
            'total_votes': total_votes_for_position,
            'candidates': []
        }
        candidates = position.candidates.all()
        for candidate in candidates:
            vote_count = Vote.objects.filter(election=election, position=position, candidate=candidate).count()
            percentage = (vote_count / total_votes_for_position * 100) if total_votes_for_position > 0 else 0
            photo_url = None
            if candidate.photo and request:
                photo_url = request.build_absolute_uri(candidate.photo.url)
            position_info['candidates'].append({
                'candidate_id': str(candidate.id),
                'name': candidate.name,
                'photo': photo_url,
                'vote_count': vote_count,
                'percentage': round(percentage, 2)
            })
        candidates_list = position_info['candidates']
        if candidates_list:
            max_votes = max(c['vote_count'] for c in candidates_list)
            if max_votes > 0:
                for c in candidates_list:
                    if c['vote_count'] == max_votes:
                        if election.status == 'COMPLETED':
                            c['is_winner'] = True
                        elif election.status == 'ACTIVE':
                            c['is_leading'] = True
        results_data['positions'].append(position_info)
    return results_data


def get_user_organization(request):
    if hasattr(request, 'organization') and request.organization:
        return request.organization
    if request.user.is_authenticated and request.user.organization:
        return request.user.organization
    return None


class BaseOrganizationViewSet(viewsets.ModelViewSet):
    def get_queryset(self):
        queryset = super().get_queryset()
        if hasattr(queryset.model, 'organization'):
            org = get_user_organization(self.request)
            if org:
                queryset = queryset.filter(organization=org)
            elif not self.request.user.is_superuser:
                return queryset.model.objects.none()
            org_id = self.request.query_params.get('organization_id')
            if org_id:
                queryset = queryset.filter(organization_id=org_id)
        if hasattr(queryset.model, 'is_deleted'):
            queryset = queryset.filter(is_deleted=False)
        return queryset

    def perform_create(self, serializer):
        org = get_user_organization(self.request)
        if not org and not self.request.user.is_superuser:
            raise serializers.ValidationError({'organization': 'Organization is required.'})
        if self.request.user.is_superuser and 'organization' in self.request.data:
            org_id = self.request.data.get('organization')
            if org_id:
                try:
                    org = Organization.objects.get(id=org_id, is_deleted=False, status='ACTIVE')
                except Organization.DoesNotExist:
                    raise serializers.ValidationError({'organization': 'Invalid organization.'})
        instance = serializer.save(organization=org)
        log_audit(
            user=self.request.user,
            action='CREATE',
            model_name=serializer.Meta.model.__name__,
            object_id=instance.pk,
            organization=org,
            request=self.request
        )

    def perform_update(self, serializer):
        instance = serializer.save()
        log_audit(
            user=self.request.user,
            action='UPDATE',
            model_name=serializer.Meta.model.__name__,
            object_id=instance.pk,
            organization=get_user_organization(self.request),
            request=self.request
        )

    def perform_destroy(self, instance):
        log_audit(
            user=self.request.user,
            action='DELETE',
            model_name=instance.__class__.__name__,
            object_id=instance.pk,
            organization=get_user_organization(self.request),
            request=self.request
        )
        instance.delete()


class ElectionViewSet(BaseOrganizationViewSet):
    queryset = Election.objects.filter(is_deleted=False)
    serializer_class = ElectionSerializer

    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'vote', 'results',
                           'results_pdf', 'results_csv', 'results_json',
                           'my_voted_positions', 'vote_timeline']:
            permission_classes = [IsAuthenticated]
        else:
            permission_classes = [IsAuthenticated, IsNotVoter]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        queryset = super().get_queryset()
        now = timezone.now()
        past_due = queryset.filter(status='ACTIVE', end_date__lt=now)
        if past_due.exists():
            past_due.update(status='COMPLETED', end_date=now)
            for election in past_due:
                log_audit(
                    user=None,
                    action='AUTO_COMPLETED',
                    model_name='Election',
                    object_id=election.pk,
                    organization=election.organization,
                    details={'reason': 'End date passed'},
                )
        return super().get_queryset()

    def perform_create(self, serializer):
        org = get_user_organization(self.request)
        if not org and not self.request.user.is_superuser:
            raise serializers.ValidationError({'organization': 'Organization is required.'})
        if self.request.user.is_superuser and 'organization' in self.request.data:
            org_id = self.request.data.get('organization')
            if org_id:
                try:
                    org = Organization.objects.get(id=org_id, is_deleted=False, status='ACTIVE')
                except Organization.DoesNotExist:
                    raise serializers.ValidationError({'organization': 'Invalid organization.'})

        if org and not self.request.user.is_superuser:
            current_election_count = Election.objects.filter(
                organization=org, is_deleted=False
            ).count()
            if current_election_count >= org.max_elections:
                raise serializers.ValidationError({
                    'plan_limit': f'Your plan allows a maximum of {org.max_elections} election(s). You currently have {current_election_count}. Please upgrade to create more.'
                })

        instance = serializer.save(organization=org, created_by=self.request.user)
        log_audit(
            user=self.request.user,
            action='CREATE',
            model_name='Election',
            object_id=instance.pk,
            organization=org,
            request=self.request
        )

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        election = self.get_object()
        if election.status not in ['DRAFT', 'SCHEDULED']:
            return Response({"error": "Election can only be started from DRAFT or SCHEDULED."}, status=400)
        election.status = 'ACTIVE'
        election.start_date = timezone.now()
        election.save()
        log_audit(request.user, 'UPDATE', 'Election', election.pk, organization=election.organization, details={'status': 'ACTIVE'}, request=request)
        return Response({"message": "Election started"})

    @action(detail=True, methods=['post'])
    def end(self, request, pk=None):
        election = self.get_object()
        if election.status != 'ACTIVE':
            return Response({"error": "Only active elections can be ended."}, status=400)
        election.status = 'COMPLETED'
        election.end_date = timezone.now()
        election.save()
        log_audit(request.user, 'UPDATE', 'Election', election.pk, organization=election.organization, details={'status': 'COMPLETED'}, request=request)
        return Response({"message": "Election ended"})

    @action(detail=True, methods=['post'])
    def vote(self, request, pk=None):
        election = self.get_object()
        if election.status != 'ACTIVE':
            return Response({"error": "Voting is only allowed in active elections."}, status=400)

        voter = getattr(request.user, 'voter_profile', None)
        if not voter or not voter.is_verified:
            return Response({"error": "Verified voter profile required."}, status=403)

        serializer = VoteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        position = serializer.validated_data['position']
        if position.election != election:
            return Response({"error": "Position does not belong to this election."}, status=400)

        if VoterRecord.objects.filter(voter=voter, election=election, position=position).exists():
            return Response({"error": "You have already voted for this position."}, status=403)

        import hashlib, uuid
        vote_hash = hashlib.sha256(f"{voter.id}{election.id}{uuid.uuid4()}".encode()).hexdigest()

        vote = serializer.save(
            organization=election.organization,
            election=election,
            vote_hash=vote_hash,
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')
        )

        VoterRecord.objects.create(
            organization=election.organization,
            voter=voter,
            election=election,
            position=position,
            vote_hash=vote_hash,
            ip_address=request.META.get('REMOTE_ADDR')
        )
        voter.has_voted = True
        voter.save()
        return Response({"message": "Vote recorded"}, status=201)

    @action(detail=True, methods=['get'])
    def results(self, request, pk=None):
        election = self.get_object()
        data = get_election_results(election, request)
        return Response(data)

    @action(detail=True, methods=['get'])
    def vote_timeline(self, request, pk=None):
        election = self.get_object()
        org = election.organization
        if org.plan != 'ENTERPRISE':
            return Response({"error": "Advanced analytics is an Enterprise feature."}, status=403)

        votes = Vote.objects.filter(election=election).order_by('voted_at')
        if not votes.exists():
            return Response([])

        start = votes.first().voted_at
        end = votes.last().voted_at
        timeline = defaultdict(int)

        for vote in votes:
            hour = vote.voted_at.replace(minute=0, second=0, microsecond=0)
            timeline[hour] += 1

        result = []
        current = start.replace(minute=0, second=0, microsecond=0)
        while current <= end:
            result.append({
                'hour': current.isoformat(),
                'votes': timeline.get(current, 0),
            })
            current += timedelta(hours=1)

        return Response(result)

    @action(detail=True, methods=['get'])
    def my_voted_positions(self, request, pk=None):
        election = self.get_object()
        voter = getattr(request.user, 'voter_profile', None)
        if not voter:
            return Response([])
        records = VoterRecord.objects.filter(
            voter=voter, election=election
        ).values_list('position_id', flat=True)
        return Response(records)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsOrgAdmin])
    def enable_sharing(self, request, pk=None):
        election = self.get_object()
        org = election.organization

        # Free plan: allow only once
        if org.plan == 'FREE':
            if org.free_results_downloads_used >= 1:
                return Response({"error": "You've used your free share. Upgrade to continue."}, status=403)

        link, created = ElectionShareLink.objects.update_or_create(
            election=election,
            defaults={'is_active': True, 'expires_at': None}
        )
        frontend_base = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')
        share_url = f'{frontend_base}/share/{link.token}/'

        # Increment free usage counter
        if org.plan == 'FREE':
            org.free_results_downloads_used += 1
            org.save()

        return Response({'share_url': share_url, 'token': str(link.token)})

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated, IsOrgAdmin])
    def disable_sharing(self, request, pk=None):
        election = self.get_object()
        try:
            link = election.share_link
            link.is_active = False
            link.save()
        except ElectionShareLink.DoesNotExist:
            pass
        return Response({"message": "Sharing disabled."})

    @action(detail=True, methods=['get'], authentication_classes=[QueryParamJWTAuthentication], permission_classes=[IsAuthenticated])
    def results_pdf(self, request, pk=None):
        election = self.get_object()
        org = election.organization

        # Free plan: allow only one PDF download
        if org.plan == 'FREE':
            if org.free_results_downloads_used >= 1:
                return Response({"error": "You've used your free PDF download. Upgrade to continue."}, status=403)

        response = generate_election_results_pdf(election, request)

        # Increment free usage counter
        if org.plan == 'FREE':
            org.free_results_downloads_used += 1
            org.save()

        return response

    @action(detail=True, methods=['get'], authentication_classes=[QueryParamJWTAuthentication], permission_classes=[IsAuthenticated])
    def results_csv(self, request, pk=None):
        election = self.get_object()
        org = election.organization

        eligible_voters = Voter.objects.filter(
            organization=org, is_active=True, is_verified=True
        ).count()
        total_votes_cast = VoterRecord.objects.filter(
            election=election
        ).values('voter').distinct().count()
        remaining = eligible_voters - total_votes_cast
        turnout_percent = (total_votes_cast / eligible_voters * 100) if eligible_voters > 0 else 0

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{election.title}_results.csv"'

        writer = csv.writer(response)
        writer.writerow(['Election Title', election.title])
        writer.writerow(['Status', election.status])
        writer.writerow(['Eligible Voters', eligible_voters])
        writer.writerow(['Votes Cast', total_votes_cast])
        writer.writerow(['Remaining', remaining])
        writer.writerow(['Turnout %', f'{turnout_percent:.1f}%'])
        writer.writerow([])

        positions = election.positions.all()
        for position in positions:
            pos_total = Vote.objects.filter(election=election, position=position).count()
            writer.writerow([f'Position: {position.title}'])
            writer.writerow(['Total Votes', pos_total])
            writer.writerow(['Candidate', 'Votes', 'Percentage'])
            candidates = position.candidates.all()
            for cand in candidates:
                vote_count = Vote.objects.filter(
                    election=election, position=position, candidate=cand
                ).count()
                perc = (vote_count / pos_total * 100) if pos_total > 0 else 0
                writer.writerow([cand.name, vote_count, f'{perc:.1f}%'])
            writer.writerow([])

        return response

    @action(detail=True, methods=['get'], authentication_classes=[QueryParamJWTAuthentication], permission_classes=[IsAuthenticated])
    def results_json(self, request, pk=None):
        election = self.get_object()
        response = self.results(request, pk)
        response['Content-Disposition'] = f'attachment; filename="{election.title}_results.json"'
        return response


class PositionViewSet(BaseOrganizationViewSet):
    queryset = Position.objects.all()
    serializer_class = PositionSerializer

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            permission_classes = [IsAuthenticated]
        else:
            permission_classes = [IsAuthenticated, IsNotVoter]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        qs = super().get_queryset()
        election_id = self.request.query_params.get('election_id')
        if election_id:
            qs = qs.filter(election_id=election_id)
        return qs


class CandidateViewSet(BaseOrganizationViewSet):
    queryset = Candidate.objects.all()
    serializer_class = CandidateSerializer
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            permission_classes = [IsAuthenticated]
        else:
            permission_classes = [IsAuthenticated, IsNotVoter]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        qs = super().get_queryset()
        position_id = self.request.query_params.get('position_id')
        if position_id:
            qs = qs.filter(position_id=position_id)
        return qs

    def perform_create(self, serializer):
        position_id = self.request.data.get('position')
        if not position_id:
            raise serializers.ValidationError({'position': 'Position is required.'})
        try:
            position = Position.objects.get(pk=position_id)
        except Position.DoesNotExist:
            raise serializers.ValidationError({'position': 'Invalid position.'})

        election = position.election
        if election.status not in ['DRAFT', 'SCHEDULED']:
            raise serializers.ValidationError({'election': 'Candidates can only be added to draft or scheduled elections.'})

        # Get organisation from the election
        org = election.organization

        # Save with organisation, active and approved flags
        serializer.save(
            organization=org,
            is_active=True,
            is_approved=True,
        )


class VoterViewSet(BaseOrganizationViewSet):
    queryset = Voter.objects.all()
    serializer_class = VoterSerializer
    permission_classes = [IsAuthenticated, IsNotVoter]
    pagination_class = None

    @action(detail=False, methods=['post'], url_path='upload-csv', permission_classes=[IsAuthenticated, IsOrgAdmin])
    def upload_csv(self, request):
        org = get_user_organization(request)
        if not org:
            return Response({"error": "No organization found."}, status=400)
        if request.user.role not in ['ORG_ADMIN', 'SUPER_ADMIN']:
            return Response({"error": "Only admins can upload voters."}, status=403)

        current_voter_count = Voter.objects.filter(
            organization=org, is_active=True, is_verified=True
        ).count()
        if current_voter_count >= org.max_voters:
            return Response(
                {"error": f"Your plan allows a maximum of {org.max_voters} voters. You already have {current_voter_count}. Please upgrade to add more."},
                status=403
            )

        serializer = VoterCSVUploadSerializer(data=request.data, context={'organization': org})
        if serializer.is_valid():
            result = serializer.save()
            log_audit(
                user=request.user,
                action='UPLOAD_VOTERS',
                model_name='Voter',
                object_id=f"CSV upload ({result['created']} voters)",
                organization=org,
                details={'created': result['created'], 'errors': result['errors']},
                request=request
            )
            return Response(result, status=201)
        return Response(serializer.errors, status=400)

    @action(detail=False, methods=['post'], url_path='send-invitations', permission_classes=[IsAuthenticated, IsOrgAdmin])
    def send_invitations(self, request):
        org = get_user_organization(request)
        if not org:
            return Response({"error": "No organization found."}, status=400)

        if org.plan == 'FREE':
            return Response(
                {"error": "Email invitations are available on Standard and Enterprise plans."},
                status=403
            )

        serializer = VoterInvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if serializer.validated_data.get('send_all'):
            voters = Voter.objects.filter(organization=org, is_verified=True, is_active=True)
        else:
            voter_ids = serializer.validated_data['voter_ids']
            voters = Voter.objects.filter(id__in=voter_ids, organization=org, is_verified=True, is_active=True)

        invited_count = 0
        for voter in voters:
            subject = f"Vote Now – {org.name}"
            message = (
                f"Hello {voter.first_name},\n\n"
                f"You have been invited to vote in an election organized by {org.name}.\n"
                f"Please log in using your email ({voter.email}) and the default password 'Vote@123' (unless you changed it).\n\n"
                f"Voting Portal: {request.build_absolute_uri('/vote/login')}\n\n"
                f"Thank you for participating."
            )
            try:
                send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [voter.email])
                invited_count += 1
            except Exception:
                pass

        return Response({"message": f"Invitations sent to {invited_count} voter(s)."})

    @action(detail=False, methods=['post'], url_path='send-sms-invitations', permission_classes=[IsAuthenticated, IsOrgAdmin])
    def send_sms_invitations(self, request):
        org = get_user_organization(request)
        if not org:
            return Response({"error": "No organization found."}, status=400)

        if org.plan != 'ENTERPRISE':
            return Response({"error": "SMS invitations are an Enterprise feature."}, status=403)

        serializer = VoterInvitationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if serializer.validated_data.get('send_all'):
            voters = Voter.objects.filter(organization=org, is_verified=True, is_active=True)
        else:
            voter_ids = serializer.validated_data['voter_ids']
            voters = Voter.objects.filter(id__in=voter_ids, organization=org, is_verified=True, is_active=True)

        gateway_url = settings.SMS_GATEWAY_URL
        api_key = settings.SMS_API_KEY
        sender_id = settings.SMS_SENDER_ID

        sent_count = 0
        for voter in voters:
            if not voter.phone:
                continue
            message_body = (
                f"Hello {voter.first_name}, you have been invited to vote in {org.name}. "
                f"Log in with email {voter.email} and password 'Vote@123' (unless changed). "
                f"Voting portal: {request.build_absolute_uri('/vote/login')}"
            )
            payload = {
                'from': sender_id,
                'to': voter.phone,
                'content': message_body,
            }
            headers = {
                'Authorization': f'Basic {api_key}',
                'Content-Type': 'application/json',
            }
            try:
                response = requests.post(gateway_url, json=payload, headers=headers)
                if response.status_code in (200, 201):
                    sent_count += 1
            except Exception:
                pass

        return Response({"message": f"SMS invitations sent to {sent_count} voter(s)."})


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSuperAdmin])
def system_stats(request):
    stats = {
        'total_organizations': Organization.objects.filter(is_deleted=False).count(),
        'total_elections': Election.objects.filter(is_deleted=False).count(),
        'active_elections': Election.objects.filter(is_deleted=False, status='ACTIVE').count(),
        'completed_elections': Election.objects.filter(is_deleted=False, status='COMPLETED').count(),
        'total_positions': Position.objects.count(),
        'total_candidates': Candidate.objects.count(),
        'total_voters': Voter.objects.count(),
    }
    return Response(stats)