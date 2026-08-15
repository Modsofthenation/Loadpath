import graphene
import strawberry

from billing.models import Invoice


@strawberry.type
class InvoiceType:
    id: int
    total: float
    status: str


@strawberry.type
class Query:
    @strawberry.field
    def invoice(self, id: int) -> InvoiceType:
        row = Invoice.objects.get(pk=id)
        return InvoiceType(id=row.id, total=float(row.total), status=row.status)


schema = strawberry.Schema(query=Query)


class CreditInvoice(graphene.Mutation):
    class Arguments:
        id = graphene.ID(required=True)

    ok = graphene.Boolean()

    def mutate(self, info, id):
        Invoice.objects.filter(pk=id).update(status="credited")
        return CreditInvoice(ok=True)


class Mutation(graphene.ObjectType):
    credit_invoice = CreditInvoice.Field()
